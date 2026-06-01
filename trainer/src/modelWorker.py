import pika
import json
import time
import asyncio
import logging
from uuid import UUID
from pathlib import Path

from .config.config import config
from .db.db_client import DBClient
from .db.s3_client import S3Client
from .db.dataset_builder import DatasetBuilder
from .model_factory import ModelFactory
from .comet_ml.tracker import ExperimentTracker

logger = logging.getLogger("trainer.worker")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

class TrainerWorker:
    def __init__(self):
        # Note: DBClient is NOT stored here. A fresh DBClient is created per job
        # in process_job() because asyncio.run() creates a new event loop each time,
        # and asyncpg connections cannot be shared across event loops.
        self.s3 = S3Client()
        self.factory = ModelFactory()

    async def _async_pipeline(self, job: dict, tracker: ExperimentTracker, db: "DBClient") -> None:
        model_id_str = job["model_id"]
        model_id = UUID(model_id_str)
        model_name = job["nombre"]
        piezas_config = job["piezas"] # list of {"id_pieza": str, "class_index": int}
        hyperparams = job.get("hyperparams", {})

        # Single resolution point: merge user overrides with config defaults.
        # `effective` is the authoritative hyperparam set for this run; both
        # the experiment tracker and the trainer factory consume it directly.
        effective = {
            "base_model": hyperparams.get("base_model") or config.BASE_MODEL,
            "epochs": hyperparams.get("epochs") or config.TRAIN_EPOCHS,
            "patience": hyperparams.get("patience") or config.TRAIN_PATIENCE,
            "imgsz": hyperparams.get("imgsz") or config.TRAIN_IMGSZ,
        }

        # Initialize tracker parameters
        tracker.start_experiment(model_name, model_id_str)
        tracker.log_hyperparameters({**effective, "device": config.DEVICE})

        logger.info(f"Model {model_id_str}: Training hyperparameters: {effective}")

        # Step 1: Set database state to PREPARING_DATA
        logger.info(f"Model {model_id_str}: Updating database status to PREPARING_DATA")
        await db.update_model_status(model_id, "PREPARING_DATA")

        # Step 2: Build dataset
        logger.info(f"Model {model_id_str}: Assembling and remapping datasets on local disk")
        dataset_builder = DatasetBuilder(self.s3, config.WORKSPACE_DIR)
        
        piece_names = []
        for p_cfg in piezas_config:
            piece_uuid = UUID(p_cfg["id_pieza"])
            class_index = p_cfg["class_index"]
            
            piece_name = await db.get_piece_name(piece_uuid)
            samples = await db.get_training_samples(piece_uuid)
            
            piece_names.append(piece_name)
            logger.info(f"Piece: '{piece_name}' ({piece_uuid}) has {len(samples)} annotated samples.")
            
            dataset_builder.add_piece(
                piece_id=str(piece_uuid),
                class_index=class_index,
                class_name=piece_name,
                samples=samples
            )

        # Download files, remap classes, and save dataset.yaml
        dataset = dataset_builder.build()
        tracker.log_dataset_info(dataset)
        tracker.add_tags(piece_names + ["yolov8-seg"])

        # Step 3: Set database state to TRAINING
        logger.info(f"Model {model_id_str}: Dataset built successfully. Updating database status to TRAINING.")
        await db.update_model_status(model_id, "TRAINING")

        try:
            # Step 4: Run training
            logger.info(f"Model {model_id_str}: Initiating YOLOv8n-seg trainer.")
            result = self.factory.train(dataset, model_id_str, effective)
            tracker.log_training_result(result)

            # Step 5: Upload trained weights to S3
            s3_weights_key = f"models/{model_id_str}/best.pt"
            logger.info(f"Model {model_id_str}: Uploading best.pt weights to S3 key '{s3_weights_key}'...")
            self.s3.upload_file(result.best_weights, s3_weights_key)

            # Step 6: Mark database status as COMPLETED
            await db.update_model_status(model_id, "COMPLETED", s3_weights_key)
            logger.info(f"Model {model_id_str}: Status updated to COMPLETED.")

        finally:
            # Ensure local disk cleanup executes under all circumstances
            logger.info(f"Model {model_id_str}: Cleaning up dataset cache directory.")
            dataset.cleanup()

    async def _update_failed_status(self, model_id: UUID) -> None:
        """Update model status to FAILED. Called within the same event loop."""
        try:
            await self.db.update_model_status(model_id, "FAILED")
        except Exception as db_err:
            logger.error(f"Could not update model state to FAILED in database: {db_err}")

    def process_job(self, job: dict) -> None:
        """Runs the async pipeline from a synchronous consumer frame.
        
        A fresh DBClient is created for each job so that the SQLAlchemy async
        engine (and its underlying asyncpg connections) are fully contained
        within a single asyncio.run() event loop. Re-using an engine across
        multiple asyncio.run() calls causes asyncpg's InterfaceError because
        connections are bound to the event loop they were created in.
        """
        tracker = ExperimentTracker()
<<<<<<< HEAD
        db = DBClient()  # Fresh engine per job — must not be shared across asyncio.run() calls
=======
        model_id_str = job.get("model_id")
        model_id = UUID(model_id_str) if model_id_str else None
        
>>>>>>> 517e301fa4ef951550b1809d476b8b884d833755
        try:
            asyncio.run(self._async_pipeline(job, tracker, db))
            tracker.end_experiment()
        except Exception as e:
            logger.error(f"Pipeline error occurred during training model {model_id_str}: {e}", exc_info=True)
            tracker.log_failure(e)
            tracker.end_experiment()
            
<<<<<<< HEAD
            # Safely attempt database correction to FAILED state using a fresh client
            try:
                model_uuid = UUID(job["model_id"])
                fail_db = DBClient()
                asyncio.run(fail_db.update_model_status(model_uuid, "FAILED"))
            except Exception as db_err:
                logger.error(f"Could not update model state to FAILED in database: {db_err}")
=======
            # Update DB to FAILED inside a fresh event loop
            if model_id:
                try:
                    asyncio.run(self._update_failed_status(model_id))
                except RuntimeError:
                    # If there's already a running loop, use a new one
                    loop = asyncio.new_event_loop()
                    try:
                        loop.run_until_complete(self._update_failed_status(model_id))
                    finally:
                        loop.close()
>>>>>>> 517e301fa4ef951550b1809d476b8b884d833755

    def start_consuming(self) -> None:
        """RabbitMQ continuous connection listener with automated connection recovery."""
        connection_params = pika.ConnectionParameters(
            host=config.RABBITMQ_HOST,
            heartbeat=0,                      # Disabled — completely prevents timeout drops during long training runs
            blocked_connection_timeout=None  # Disabled
        )

        while True:
            try:
                logger.info(f"Connecting to RabbitMQ broker at host '{config.RABBITMQ_HOST}'...")
                connection = pika.BlockingConnection(connection_params)
                channel = connection.channel()
                
                # Assert queue parameters
                channel.queue_declare(queue=config.RABBITMQ_QUEUE, durable=True)
                channel.basic_qos(prefetch_count=1)
                
                logger.info(f"Queue '{config.RABBITMQ_QUEUE}' locked. Consumer active and listening...")
                
                def on_message(ch, method, properties, body):
                    delivery_tag = method.delivery_tag
                    try:
                        logger.info("Acquired a new model training job.")
                        job = json.loads(body.decode("utf-8"))
                        self.process_job(job)
                        # Only ACK if processing succeeded
                        ch.basic_ack(delivery_tag=delivery_tag)
                        logger.info("Message acknowledged after successful processing.")
                    except Exception as parse_err:
                        logger.error(f"Unable to process message payload: {parse_err}")
                        # NACK without requeue — prevents infinite retry loops on persistent failures
                        ch.basic_nack(delivery_tag=delivery_tag, requeue=False)
                        logger.info("Message rejected (nack) due to processing error.")

                channel.basic_consume(
                    queue=config.RABBITMQ_QUEUE,
                    on_message_callback=on_message
                )
                channel.start_consuming()

            except pika.exceptions.AMQPConnectionError as conn_err:
                logger.warning(f"RabbitMQ connection failed: {conn_err}. Re-establishing in 10 seconds...")
                time.sleep(10)
            except KeyboardInterrupt:
                logger.info("Worker manual interrupt shutdown triggered.")
                break
            except Exception as e:
                logger.critical(f"Critical Worker runtime crash: {e}. Restarting daemon in 10 seconds...", exc_info=True)
                time.sleep(10)

def main():
    worker = TrainerWorker()
    worker.start_consuming()

if __name__ == "__main__":
    main()