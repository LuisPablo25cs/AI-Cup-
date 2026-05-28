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
        self.db = DBClient()
        self.s3 = S3Client()
        self.factory = ModelFactory()

    async def _async_pipeline(self, job: dict, tracker: ExperimentTracker) -> None:
        model_id_str = job["model_id"]
        model_id = UUID(model_id_str)
        model_name = job["nombre"]
        piezas_config = job["piezas"] # list of {"id_pieza": str, "class_index": int}
        hyperparams = job.get("hyperparams", {})

        effective = {
            "base_model": hyperparams.get("base_model", config.BASE_MODEL),
            "train_epochs": hyperparams.get("epochs", config.TRAIN_EPOCHS),
            "train_patience": hyperparams.get("patience", config.TRAIN_PATIENCE),
            "train_imgsz": hyperparams.get("imgsz", config.TRAIN_IMGSZ),
            "device": config.DEVICE,
        }

        # Initialize tracker parameters
        tracker.start_experiment(model_name, model_id_str)
        tracker.log_hyperparameters(effective)

        logger.info(f"Model {model_id_str}: Training hyperparameters: {effective}")

        # Step 1: Set database state to PREPARING_DATA
        logger.info(f"Model {model_id_str}: Updating database status to PREPARING_DATA")
        await self.db.update_model_status(model_id, "PREPARING_DATA")

        # Step 2: Build dataset
        logger.info(f"Model {model_id_str}: Assembling and remapping datasets on local disk")
        dataset_builder = DatasetBuilder(self.s3, config.WORKSPACE_DIR)
        
        piece_names = []
        for p_cfg in piezas_config:
            piece_uuid = UUID(p_cfg["id_pieza"])
            class_index = p_cfg["class_index"]
            
            piece_name = await self.db.get_piece_name(piece_uuid)
            samples = await self.db.get_training_samples(piece_uuid)
            
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
        await self.db.update_model_status(model_id, "TRAINING")

        try:
            # Step 4: Run training
            logger.info(f"Model {model_id_str}: Initiating YOLOv8n-seg trainer.")
            result = self.factory.train(dataset, model_id_str, hyperparams)
            tracker.log_training_result(result)

            # Step 5: Upload trained weights to S3
            s3_weights_key = f"models/{model_id_str}/best.pt"
            logger.info(f"Model {model_id_str}: Uploading best.pt weights to S3 key '{s3_weights_key}'...")
            self.s3.upload_file(result.best_weights, s3_weights_key)

            # Step 6: Mark database status as COMPLETED
            await self.db.update_model_status(model_id, "COMPLETED", s3_weights_key)
            logger.info(f"Model {model_id_str}: Status updated to COMPLETED.")

        finally:
            # Ensure local disk cleanup executes under all circumstances
            logger.info(f"Model {model_id_str}: Cleaning up dataset cache directory.")
            dataset.cleanup()

    def process_job(self, job: dict) -> None:
        """Runs the async pipeline from a synchronous consumer frame."""
        tracker = ExperimentTracker()
        try:
            asyncio.run(self._async_pipeline(job, tracker))
            tracker.end_experiment()
        except Exception as e:
            logger.error(f"Pipeline error occurred during training model {job.get('model_id')}: {e}", exc_info=True)
            tracker.log_failure(e)
            tracker.end_experiment()
            
            # Safely attempt database correction to FAILED state
            try:
                model_uuid = UUID(job["model_id"])
                asyncio.run(self.db.update_model_status(model_uuid, "FAILED"))
            except Exception as db_err:
                logger.error(f"Could not update model state to FAILED in database: {db_err}")

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
                    try:
                        logger.info("Acquired a new model training job.")
                        job = json.loads(body.decode("utf-8"))
                        self.process_job(job)
                    except Exception as parse_err:
                        logger.error(f"Unable to parse message payload: {parse_err}")
                    finally:
                        # Secure ACK boundary
                        ch.basic_ack(delivery_tag=method.delivery_tag)
                        logger.info("Message acknowledged.")

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