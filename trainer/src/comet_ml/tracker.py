import logging
import traceback
from typing import Dict, Any, List
from ..config.config import config
from ..db.dataset_builder import Dataset

logger = logging.getLogger("trainer.tracker")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

class ExperimentTracker:
    def __init__(self):
        self.api_key = config.COMET_API_KEY
        self.project_name = config.COMET_PROJECT_NAME
        self.workspace = config.COMET_WORKSPACE
        self.experiment = None

        if self.api_key:
            try:
                # Dynamic imports to keep local dependencies optional
                import comet_ml
                logger.info("Initializing CometML experiment logger.")
                self.experiment = comet_ml.Experiment(
                    api_key=self.api_key,
                    project_name=self.project_name,
                    workspace=self.workspace,
                    auto_param_logging=True,
                    auto_metric_logging=True
                )
            except Exception as e:
                logger.error(f"Failed to bootstrap CometML. Defaulting to Console tracker: {e}")
                self.experiment = None
        else:
            logger.info("CometML key omitted. Fallback Console logger engaged.")

    def start_experiment(self, model_name: str, model_id: str) -> None:
        if self.experiment:
            self.experiment.set_name(f"{model_name}_{model_id}")
            self.experiment.log_other("model_id", model_id)
            self.experiment.log_other("model_name", model_name)
        else:
            logger.info(f"=== Experiment Started: {model_name} (ID: {model_id}) ===")

    def log_dataset_info(self, dataset: Dataset) -> None:
        meta = {
            "dataset_fingerprint": dataset.fingerprint,
            "dataset_dir": str(dataset.root_dir),
            "num_train_images": dataset.num_train,
            "num_val_images": dataset.num_val,
            "class_names": str(dataset.class_names)
        }
        if self.experiment:
            for k, v in meta.items():
                self.experiment.log_other(k, v)
        else:
            logger.info("--- Dataset Information ---")
            for k, v in meta.items():
                logger.info(f"  {k}: {v}")

    def log_hyperparameters(self, params: Dict[str, Any]) -> None:
        if self.experiment:
            self.experiment.log_parameters(params)
        else:
            logger.info("--- Hyperparameters ---")
            for k, v in params.items():
                logger.info(f"  {k}: {v}")

    def log_training_result(self, result: Any) -> None:
        if self.experiment:
            self.experiment.log_metrics(result.metrics)
            self.experiment.log_other("epochs_completed", result.epochs_completed)
        else:
            logger.info("--- Training Metrics ---")
            logger.info(f"  Epochs Completed: {result.epochs_completed}")
            for k, v in result.metrics.items():
                logger.info(f"    {k}: {v}")

    def add_tags(self, tags: List[str]) -> None:
        if self.experiment:
            self.experiment.add_tags(tags)
        else:
            logger.info(f"Experiment Tags: {tags}")

    def log_failure(self, error: Exception) -> None:
        tb = traceback.format_exc()
        if self.experiment:
            self.experiment.log_other("status", "FAILED")
            self.experiment.log_other("error", str(error))
            self.experiment.log_text(tb, filename="error_traceback.txt")
        else:
            logger.error("=== Experiment Execution Failure ===")
            logger.error(f"Error: {error}")
            logger.error(tb)

    def end_experiment(self) -> None:
        if self.experiment:
            self.experiment.end()
            logger.info("CometML experiment finalized and uploaded.")
        else:
            logger.info("=== Experiment Finished ===")