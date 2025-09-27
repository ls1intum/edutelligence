from unittest.mock import Mock


def mock_get_llm_config(*args, **kwargs):

    mock_config = Mock()
    mock_config.models = Mock()
    mock_config.models.base_model_config = Mock()
    mock_config.models.mini_model_config = Mock()
    mock_config.models.fast_reasoning_model_config = Mock()
    mock_config.models.long_reasoning_model_config = Mock()
    
    for model_config in [mock_config.models.base_model_config, 
                        mock_config.models.mini_model_config,
                        mock_config.models.fast_reasoning_model_config,
                        mock_config.models.long_reasoning_model_config]:
        model_config.get_model.return_value = Mock()
        model_config.supports_system_messages.return_value = True
        model_config.supports_function_calling.return_value = True
        model_config.supports_structured_output.return_value = True
    
    return mock_config 