import httpx
import logging
from typing import List, Dict, Any, Optional
from config import AgentConfig
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class Course(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    semester: Optional[str] = None


class Exercise(BaseModel):
    id: int
    title: str
    problem_statement: Optional[str] = None
    max_points: Optional[float] = None
    course: Optional[Course] = None


class CompetencyMapping(BaseModel):
    competency_id: str
    exercise_id: int
    course_id: str


class ArtemisAPIClient:
    """Client for interacting with Artemis API for course and exercise operations."""
    
    def __init__(self, base_url: str = None, api_token: str = None):
        self.base_url = base_url or AgentConfig.ARTEMIS_API_URL or "http://localhost:8080"
        self.api_token = api_token or AgentConfig.ARTEMIS_API_TOKEN
        
        if not self.api_token:
            logger.warning("No Artemis API token provided - requests may fail")
        
        self.headers = {
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        
        if self.api_token:
            self.headers["Authorization"] = f"Bearer {self.api_token}"
    
    def get_courses(self, instructor_id: Optional[int] = None) -> List[Course]:
        """Get courses accessible to the instructor.
        
        Args:
            instructor_id: Optional instructor ID filter
            
        Returns:
            List of courses
        """
        try:
            url = f"{self.base_url}/api/courses"
            if instructor_id:
                url += f"?instructorId={instructor_id}"
            
            logger.info("Fetching courses from Artemis")

            with httpx.Client(timeout=30.0) as client:
                response = client.get(url, headers=self.headers)
                
                if response.status_code != 200:
                    logger.error(f"Artemis API error: {response.status_code} - {response.text}")
                    raise Exception(f"Artemis API returned {response.status_code}: {response.text}")
                
                courses_data = response.json()
                courses = [Course(**course) for course in courses_data]
                
                logger.info(f"Retrieved {len(courses)} courses")
                return courses
                
        except Exception as e:
            logger.error(f"Failed to get courses: {str(e)}")
            raise Exception(f"Failed to get courses: {str(e)}")
    
    def get_exercises(self, course_id: str) -> List[Exercise]:
        """Get exercises for a specific course.
        
        Args:
            course_id: ID of the course
            
        Returns:
            List of exercises
        """
        try:
            url = f"{self.base_url}/api/courses/{course_id}/exercises"
            
            logger.info(f"Fetching exercises for course {course_id}")
            
            with httpx.Client(timeout=30.0) as client:
                response = client.get(url, headers=self.headers)
                
                if response.status_code != 200:
                    logger.error(f"Artemis API error: {response.status_code} - {response.text}")
                    raise Exception(f"Artemis API returned {response.status_code}: {response.text}")
                
                exercises_data = response.json()
                exercises = [Exercise(**exercise) for exercise in exercises_data]
                
                logger.info(f"Retrieved {len(exercises)} exercises for course {course_id}")
                return exercises
                
        except Exception as e:
            logger.error(f"Failed to get exercises: {str(e)}")
            raise Exception(f"Failed to get exercises: {str(e)}")
    
    def apply_competency_mapping(self, mapping: CompetencyMapping) -> bool:
        """Apply a competency mapping to an exercise.
        
        Args:
            mapping: The competency mapping to apply
            
        Returns:
            True if successful, False otherwise
        """
        try:
            url = f"{self.base_url}/api/courses/{mapping.course_id}/exercises/{mapping.exercise_id}/competencies"
            
            payload = {
                "competencyId": mapping.competency_id,
                "exerciseId": mapping.exercise_id
            }
            
            logger.info(f"Applying competency mapping: {mapping.competency_id} -> exercise {mapping.exercise_id}")
            
            with httpx.Client(timeout=30.0) as client:
                response = client.post(
                    url,
                    headers=self.headers,
                    json=payload
                )
                
                if response.status_code not in [200, 201]:
                    logger.error(f"Artemis API error: {response.status_code} - {response.text}")
                    return False
                
                logger.info("Competency mapping applied successfully")
                return True
                
        except Exception as e:
            logger.error(f"Failed to apply competency mapping: {str(e)}")
            return False
    
    def health_check(self) -> bool:
        """Check if Artemis API is available.
        
        Returns:
            True if API is healthy, False otherwise
        """
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.get(
                    f"{self.base_url}/api/health",
                    headers={"Accept": "application/json"}
                )
                return response.status_code == 200
        except Exception as e:
            logger.error(f"Artemis health check failed: {str(e)}")
            return False
    
    def format_courses_for_display(self, courses: List[Course]) -> str:
        """Format courses for display to the user.
        
        Args:
            courses: List of courses to format
            
        Returns:
            Formatted string representation
        """
        if not courses:
            return "No courses found."
        
        formatted = "## Available Courses:\n\n"
        for course in courses:
            formatted += f"**{course.title}** (ID: {course.id})\n"
            if course.description:
                formatted += f"   - *Description:* {course.description}\n"
            if course.semester:
                formatted += f"   - *Semester:* {course.semester}\n"
            formatted += "\n"
        
        return formatted
    
    def format_exercises_for_display(self, exercises: List[Exercise]) -> str:
        """Format exercises for display to the user.
        
        Args:
            exercises: List of exercises to format
            
        Returns:
            Formatted string representation
        """
        if not exercises:
            return "No exercises found."
        
        formatted = "## Course Exercises:\n\n"
        for exercise in exercises:
            formatted += f"**{exercise.title}** (ID: {exercise.id})\n"
            if exercise.problem_statement:
                problem_snippet = exercise.problem_statement[:100] + "..." if len(exercise.problem_statement) > 100 else exercise.problem_statement
                formatted += f"   - *Problem:* {problem_snippet}\n"
            if exercise.max_points:
                formatted += f"   - *Max Points:* {exercise.max_points}\n"
            formatted += "\n"
        
        return formatted