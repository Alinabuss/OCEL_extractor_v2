import sys
import os

# Add the parent directory to the Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from config import OPENAI_KEY, AZURE_KEY, AZURE_ENDPOINT
import time
from Collector_subcomponent.Collector_instance import OCEL_heuristic_collector_component
from Refiner_subcomponent.Refiner_instance import OCEL_generative_refiner_component

# Specify folder-path to dataset
dataset_folder = "./Data/EVAL3-data/Recruitment/Test_data/"


# Specify openai-api_key and openai-model OR azure-api_key, azure_endpoint, and azure_model
api_key = OPENAI_KEY
openai_model = "gpt-5-mini-2025-08-07"
azure_api_key = AZURE_KEY
azure_endpoint = AZURE_ENDPOINT
azure_model = "gpt-5-mini-2025-08-07"
azure_api_version = '2025-03-01-preview'

    
# Definition of OCEL_event_level_extractor pipeline
def OCEL_HEU_GEN_extractor(dataset_folder, level, api_type = "openai", openai_api_key = None, openai_model = None, azure_api_key = None, azure_endpoint = None, azure_model = None, azure_api_version = None):

    OCEL_heuristic_collector_component(dataset_folder, level)
    OCEL_generative_refiner_component(dataset_folder, api_type, openai_api_key, openai_model, azure_api_key,  azure_endpoint, azure_model, azure_api_version)

if __name__ == "__main__":
    start_time = time.time()
    OCEL_HEU_GEN_extractor(dataset_folder, level = 'Test_setup', api_type = "azure", azure_api_key= azure_api_key, azure_endpoint = azure_endpoint, azure_model = azure_model, azure_api_version = azure_api_version)
    end_time = time.time()
    elapsed_time = end_time - start_time
    # Convert elapsed time to hours, minutes, and seconds
    hours, rem = divmod(elapsed_time, 3600)
    minutes, seconds = divmod(rem, 60)
    print(f"Execution time: {int(hours)}h {int(minutes)}m {int(seconds)}s")