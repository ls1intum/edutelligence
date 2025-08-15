"""ADK-based AI Agent for Atlas and Artemis integration - Main module."""

import logging
from typing import Optional
from google.adk.agents import LlmAgent
from atlasml.config import get_settings
from atlasml.adk_tools import atlas_artemis_tools


logger = logging.getLogger(__name__)

class AIAgent:
    """Main ADK-based agent for Atlas competency management and Artemis course management."""

    def __init__(self, model_name: str = "gpt-4o"):
        """Initialize the ADK agent with Azure OpenAI configuration."""

        settings = get_settings()

        # Validate configuration
        if not settings.agent.openai_api_key:
            raise ValueError("OPENAI_API_KEY environment variable is required")

        # Create the main coordinator agent
        self.agent = LlmAgent(
            name="AtlasArtemisCoordinator",
            instruction=self._get_system_instruction(),
            description="AI assistant for Atlas competency management",
            tools=atlas_artemis_tools,
        )

        # Compatibility attributes for existing code
        self.pending_confirmation = None  # ADK handles confirmations internally
        self.model_name = model_name

        logger.info("ADK AtlasArtemisAgent initialized successfully")

    def _get_system_instruction(self) -> str:
        """Get the system instruction that defines agent behavior."""
        return """You are an AI assistant that helps instructors work with Atlas competency management and Artemis course management. Your role is to:

1. Help instructors discover and map competencies to course content using Atlas
2. Facilitate changes to course structure in Artemis when approved
3. Always ask for confirmation before making any changes
4. Provide clear, structured suggestions with explanations

When suggesting competency mappings:
- Present competencies clearly with descriptions
- Explain why each competency is relevant
- Always ask "Do you want to apply this mapping?" before proceeding
- Wait for explicit confirmation (yes/accept) or rejection (no/reject)

Available tools:
- get_competency_suggestions: Get competency recommendations from Atlas
- get_courses: List available courses from Artemis  
- get_exercises: Get exercises for a specific course
- apply_competency_mapping: Apply a competency mapping (requires confirmation)
- map_competency_to_exercise: Map a competency to an exercise in Atlas
- map_competency_to_competency: Create relationships between competencies

Remember: Never make changes without explicit user confirmation. Always provide helpful, structured responses with clear explanations."""

    async def handle_prompt_async(self, user_input: str, course_id: Optional[int] = None) -> str:
        """
        Asynchronously handle a user prompt using ADK agent.

        Args:
            user_input: The user's message
            course_id: Optional course ID to set as context

        Returns:
            Agent response string
        """
        if not user_input or not user_input.strip():
            raise ValueError("User input cannot be empty")

        try:
            # Add course context to input if provided
            if course_id is not None:
                context_input = f"Course context: {course_id}\n\nUser request: {user_input}"
            else:
                context_input = user_input

            logger.info(f"Processing request: {user_input[:50]}...")

            # Use ADK agent to handle the conversation
            response = await self.agent.run(context_input)

            reply = response.text

            logger.info("Request processed successfully")
            return reply

        except Exception as e:
            logger.error(f"Failed to process prompt: {str(e)}")
            raise RuntimeError(f"Failed to process your request: {str(e)}") from e

    def handle_prompt(self, user_input: str, course_id: Optional[int] = None) -> str:
        """
        Synchronous wrapper for async prompt handling.

        Args:
            user_input: The user's message
            course_id: Optional course ID to set as context

        Returns:
            Agent response string
        """
        import asyncio
        return asyncio.run(self.handle_prompt_async(user_input, course_id))

    def reset_memory(self):
        """Reset the agent's conversation memory."""
        try:
            # Get current configuration
            current_model = self.agent.model

            # Recreate the agent with same configuration
            self.agent = LlmAgent(
                name="AtlasArtemisCoordinator",
                model=current_model,
                instruction=self._get_system_instruction(),
                description="AI assistant for Atlas competency management and Artemis course management",
                tools=atlas_artemis_tools,
            )

            logger.info("Agent memory reset successfully")

        except Exception as e:
            logger.error(f"Failed to reset memory: {str(e)}")
            raise RuntimeError(f"Failed to reset memory: {str(e)}") from e


    @property
    def artemis_client(self):
        """Compatibility property for health checks."""
        from atlasml.clients.artemis_client import ArtemisAPIClient
        if not hasattr(self, '_artemis_client'):
            self._artemis_client = ArtemisAPIClient()
        return self._artemis_client