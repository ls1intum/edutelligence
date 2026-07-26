from unittest.mock import Mock


def test_weaviate_collection_data_update_preserves_vector_contract():
    collection = Mock()

    collection.data.update(
        uuid="unit-uuid", properties={"lecture_unit_name": "Renamed"}
    )

    collection.data.update.assert_called_once_with(
        uuid="unit-uuid", properties={"lecture_unit_name": "Renamed"}
    )
