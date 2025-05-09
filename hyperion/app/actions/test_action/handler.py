"""
Handler for the test action.
This is a sample action to demonstrate the dynamic model discovery.
"""
import asyncio
from datetime import datetime, timezone
import uuid
from typing import Callable, Awaitable

from app.actions.base_models import ResultUpdate
from app.actions.test_action.models import (
    TestActionInput,
    TestActionProgressUpdate,
    TestActionResult,
    TestItem
)

class TestActionHandler:
    """Handler for test action."""
    
    # This attribute is required for autodiscovery
    action_name = "test_action"
    
    async def handle(
        self,
        input_data: TestActionInput,
        send_update: Callable[[ResultUpdate], Awaitable[None]]
    ) -> TestActionResult:
        """Process the test action."""
        # Simulate processing with progress updates
        total_items = 5
        
        # Send initial progress update
        await send_update(TestActionProgressUpdate(
            status_message="Starting text processing",
            progress=0.0,
            items_processed=0,
            timestamp=datetime.now(timezone.utc).isoformat()
        ))
        
        # Process items with intermittent updates
        processed_items = []
        for i in range(total_items):
            # Simulate some processing time
            await asyncio.sleep(0.5)
            
            # Generate a test item
            item = TestItem(
                id=str(uuid.uuid4()),
                content=f"Processed item {i+1} for text: {input_data.text[:20]}...",
                score=0.1 * (i + 1)
            )
            processed_items.append(item)
            
            # Send progress update
            progress = ((i + 1) / total_items) * 100
            await send_update(TestActionProgressUpdate(
                status_message=f"Processing item {i+1} of {total_items}",
                progress=progress,
                items_processed=i + 1,
                timestamp=datetime.now(timezone.utc).isoformat()
            ))
        
        # Calculate total score
        total_score = sum(item.score for item in processed_items)
        
        # Return final result
        return TestActionResult(
            items=processed_items,
            summary=f"Processed {len(processed_items)} items in language '{input_data.language}'",
            total_score=total_score,
            timestamp=datetime.now(timezone.utc).isoformat()
        )