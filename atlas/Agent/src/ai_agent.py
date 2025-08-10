from openai import AzureOpenAI
from config import AgentConfig
from atlas_client import AtlasAPIClient, Competency
from artemis_client import ArtemisAPIClient, Course, Exercise, CompetencyMapping
import asyncio
import json
from typing import Dict, Any, List, Optional
import logging

logger = logging.getLogger(__name__)

class AIAgent:
    def __init__(self, model_name: str = "gpt-4o"):
        api_key = AgentConfig.OPENAI_API_KEY
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable is required")

        self.client = AzureOpenAI(
            api_key=api_key,
            api_version=AgentConfig.AZURE_API_VERSION,
            azure_endpoint=AgentConfig.AZURE_ENDPOINT
        )
        self.model_name = model_name
        self.memory = []
        
        # Initialize API clients
        self.atlas_client = AtlasAPIClient()
        self.artemis_client = ArtemisAPIClient()
        
        # Agent state
        self.pending_confirmation = None  # Store pending actions needing confirmation
        self.current_course_context = None
        
        # Initialize with system prompt
        self.system_prompt = self._create_system_prompt()
        self.memory.append({"role": "system", "content": self.system_prompt})

    def _create_system_prompt(self) -> str:
        """Create the system prompt that defines the agent's behavior."""
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

Available functions:
- get_competency_suggestions: Get competency recommendations from Atlas
- get_courses: List available courses from Artemis  
- get_exercises: Get exercises for a specific course
- apply_competency_mapping: Apply a competency mapping (requires confirmation)

Remember: Never make changes without explicit user confirmation."""

    async def handle_prompt_async(self, user_input: str) -> str:
        """
        Asynchronously handles a user prompt with function calling support.
        """
        if not user_input or not user_input.strip():
            raise ValueError("User input cannot be empty")

        # Handle confirmation responses
        if self.pending_confirmation:
            return await self._handle_confirmation(user_input)

        # Add user message to memory
        self.memory.append({"role": "user", "content": user_input})

        try:
            # Define available functions
            functions = self._get_function_definitions()

            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=self.memory,
                temperature=0.3,
                functions=functions,
                function_call="auto"
            )

            message = response.choices[0].message
            
            # Handle function calls
            if message.function_call:
                return await self._handle_function_call(message)
            else:
                reply = message.content
                if not reply:
                    reply = "I'm sorry, I didn't understand that. Could you please rephrase your request?"

                self.memory.append({"role": "assistant", "content": reply})
                return reply

        except Exception as e:
            # Remove the user message if processing fails
            self.memory.pop()
            logger.error(f"Failed to process prompt: {str(e)}")
            raise RuntimeError(f"Failed to process your request: {str(e)}") from e

    def handle_prompt(self, user_input: str) -> str:
        """
        Synchronous wrapper for async prompt handling.
        """
        return asyncio.run(self.handle_prompt_async(user_input))

    async def _handle_confirmation(self, user_input: str) -> str:
        """Handle confirmation responses from the user."""
        user_input_lower = user_input.lower().strip()
        
        if any(word in user_input_lower for word in ['yes', 'y', 'accept', 'apply', 'confirm']):
            # User confirmed - execute the pending action
            action = self.pending_confirmation
            self.pending_confirmation = None
            
            if action['type'] == 'apply_competency_mapping':
                mapping = CompetencyMapping(**action['data'])
                success = self.artemis_client.apply_competency_mapping(mapping)
                
                if success:
                    return f"✅ Successfully applied competency mapping: {action['data']['competency_id']} to exercise {action['data']['exercise_id']}"
                else:
                    return "❌ Failed to apply competency mapping. Please try again or check your permissions."
                    
        elif any(word in user_input_lower for word in ['no', 'n', 'reject', 'cancel', 'deny']):
            # User rejected
            self.pending_confirmation = None
            return "Okay, I won't apply that mapping. Is there anything else I can help you with?"
        
        else:
            # Unclear response - ask again
            return "Do you want to apply this competency mapping? (yes/no)"

    def _get_function_definitions(self) -> List[Dict[str, Any]]:
        """Define available functions for the AI agent."""
        return [
            {
                "name": "get_competency_suggestions",
                "description": "Get competency recommendations from Atlas based on a description",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "description": {"type": "string", "description": "Description to find similar competencies for"},
                        "course_id": {"type": "string", "description": "ID of the course context"}
                    },
                    "required": ["description", "course_id"]
                }
            },
            {
                "name": "get_courses",
                "description": "Get list of available courses from Artemis",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            },
            {
                "name": "get_exercises",
                "description": "Get exercises for a specific course from Artemis",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "course_id": {"type": "integer", "description": "ID of the course"}
                    },
                    "required": ["course_id"]
                }
            }
        ]

    async def _handle_function_call(self, message) -> str:
        """Handle function calls from the AI."""
        function_name = message.function_call.name
        function_args = json.loads(message.function_call.arguments)
        
        # Add the function call to memory
        self.memory.append({
            "role": "assistant", 
            "content": None,
            "function_call": {
                "name": function_name,
                "arguments": message.function_call.arguments
            }
        })
        
        try:
            # Execute the function
            if function_name == "get_competency_suggestions":
                result = await self._get_competency_suggestions(**function_args)
            elif function_name == "get_courses":
                result = self._get_courses()
            elif function_name == "get_exercises":
                result = self._get_exercises(**function_args)
            else:
                result = f"Unknown function: {function_name}"
            
            # Add function result to memory
            self.memory.append({
                "role": "function",
                "name": function_name,
                "content": str(result)
            })
            
            # Get AI response to function result
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=self.memory,
                temperature=0.3
            )
            
            reply = response.choices[0].message.content
            self.memory.append({"role": "assistant", "content": reply})
            
            return reply
            
        except Exception as e:
            error_msg = f"Error executing {function_name}: {str(e)}"
            logger.error(error_msg)
            
            # Add error to memory
            self.memory.append({
                "role": "function",
                "name": function_name,
                "content": error_msg
            })
            
            return f"I encountered an error: {error_msg}"

    async def _get_competency_suggestions(self, description: str, course_id: str) -> str:
        """Get competency suggestions from Atlas."""
        try:
            competencies = await self.atlas_client.suggest_competencies(description, course_id)
            if competencies:
                formatted = self.atlas_client.format_competencies_for_display(competencies)
                return formatted + "\n\nWould you like me to help you apply any of these competency mappings to specific exercises?"
            else:
                return "No competencies found for that description. Try with different keywords."
        except Exception as e:
            return f"Failed to get competency suggestions: {str(e)}"

    def _get_courses(self) -> str:
        """Get courses from Artemis."""
        try:
            courses = self.artemis_client.get_courses()
            if courses:
                # Store course context for later use
                self.current_course_context = courses
                return self.artemis_client.format_courses_for_display(courses)
            else:
                return "No courses found. You may not have instructor access or there might be a connectivity issue."
        except Exception as e:
            return f"Failed to get courses: {str(e)}"

    def _get_exercises(self, course_id: str) -> str:
        """Get exercises for a course."""
        try:
            exercises = self.artemis_client.get_exercises(course_id)
            if exercises:
                return self.artemis_client.format_exercises_for_display(exercises)
            else:
                return f"No exercises found for course {course_id}."
        except Exception as e:
            return f"Failed to get exercises: {str(e)}"

    def request_competency_mapping_confirmation(self, competency_id: str, exercise_id: int, course_id: str) -> str:
        """Request confirmation for applying a competency mapping."""
        self.pending_confirmation = {
            'type': 'apply_competency_mapping',
            'data': {
                'competency_id': competency_id,
                'exercise_id': exercise_id,
                'course_id': course_id
            }
        }
        return f"Do you want to apply competency '{competency_id}' to exercise {exercise_id}? (yes/no)"

    def reset_memory(self):
        """Clears the conversation history but keeps system prompt."""
        self.memory = [{"role": "system", "content": self.system_prompt}]
        self.pending_confirmation = None
        self.current_course_context = None
