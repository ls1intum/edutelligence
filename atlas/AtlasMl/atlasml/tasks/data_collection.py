"""
Data collection and embedding tasks.
"""

import logging
from datetime import datetime

from atlasml.tasks.data_collection import collect_and_embed_data

logger = logging.getLogger(__name__)


def collect_and_embed_data():
    """
    Main function to collect data and generate embeddings.
    This function will be called by the scheduler.
    """
    try:
        logger.info(f"Starting data collection and embedding at {datetime.now()}")

        # TODO: Fetch and embed data from Artemis API
        # 1. Collect data from Artemis API
        # 2. Generate embeddings
        # 3. Save embeddings to Weaviate
        # 4. Generate Medoids
        # 5. Save Medoids to Weaviate
        # 6. Generate embedings for Competencies
        # 7. Save Competencies to Weaviate
        logger.info("Data collection and embedding completed successfully")
    except Exception as e:
        logger.error(f"Error in data collection and embedding: {e!s}")
        raise


#  TODO: Discuss what should be the frequency of the data collection and embedding
# scheduler.add_daily_job(collect_and_embed_data, hour=0, minute=0)
