from typing import Type, Dict, Any, Union, List
from pydantic import BaseModel, Field
from crewai.tools import BaseTool
import requests
import os
from dotenv import load_dotenv
import logging
import re

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def limit_log_length(message, max_length=200):
    """Limit the length of a log message to max_length characters."""
    if isinstance(message, str) and len(message) > max_length:
        return message[:max_length] + "..."
    return message

load_dotenv()
TIMEOUT = int(os.getenv("TIMEOUT", "30"))
class ClickUpSchema(BaseModel):
    url: str = Field(..., description="The ClickUp resource URL to analyze")

class ClickUpTool(BaseTool):
    name: str = "analyze_clickup_resource"
    description: str = "Analyze ClickUp tasks, lists, and documents"
    args_schema: Type[BaseModel] = ClickUpSchema

    def construct_api_url(self, url: str) -> str:
        """
        Parse a ClickUp URL to extract relevant parameters and construct the API URL.
        """
        # Match pattern: /t/team_id/task_id (e.g., /t/20696747/CICD-1221)
        team_task_match = re.search(r'https://app\.clickup\.com/t/(\d+)/([\w-]+)', url)
        if team_task_match:
            team_id = team_task_match.group(1)
            task_id = team_task_match.group(2)
            api_url = f"https://api.clickup.com/api/v2/task/{task_id}?team_id={team_id}&custom_task_ids=true"
            return api_url

        # Match pattern: /team_id/v/dc/... (e.g., /20696747/v/dc/kqknb-962555/kqknb-521815)
        team_view_match = re.search(r'https://app\.clickup\.com/(\d+)/v/dc/([\w-]+)/([\w-]+)', url)
        if team_view_match:
            team_id = team_view_match.group(1)
            doc_id = team_view_match.group(2)
            view_id = team_view_match.group(3)
            api_url = f"https://api.clickup.com/api/v3/workspaces/{team_id}/docs/{doc_id}/pages?max_page_depth=-1&content_format=text%2Fmd"
            return api_url

        raise ValueError("Unsupported ClickUp URL")

    def get_task_info(self, url: str) -> Union[Dict, List]:
        """
        Retrieve information about a task or document from ClickUp.
        Returns either a dictionary or a list depending on the API response.
        """
        api_key = os.getenv("CLICKUP_API_KEY")
        if not api_key:
            raise ValueError("CLICKUP_API_KEY not found in environment variables")

        headers = {
            "Authorization": api_key,
            "Content-Type": "application/json"
        }

        try:
            logger.debug(f"Making request to: {limit_log_length(url)}")
            response = requests.get(url, headers=headers, timeout=TIMEOUT)  # Added 30 second timeout
            logger.debug(f"Response status code: {response.status_code}")

            # Log the raw response content for debugging

            response.raise_for_status()  # This will raise an HTTPError for bad responses

            # Check if response content is empty
            if not response.text.strip():
                raise Exception("Empty response received from ClickUp API")

            try:
                task_data = response.json()
                logger.debug(f"Response data type: {type(task_data)}")
                return task_data
            except requests.exceptions.JSONDecodeError as json_err:
                logger.error(f"JSON decode error: {limit_log_length(str(json_err))}")
                logger.error(f"Response content: {limit_log_length(response.text)}")
                raise Exception(f"Failed to parse JSON response: {limit_log_length(str(json_err))}, Response: {limit_log_length(response.text)}")

        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error: {limit_log_length(str(e))}")
            # Raise the original HTTPError
            raise e
        except Exception as e:
            logger.error(f"Error in get_task_info: {limit_log_length(str(e))}")
            raise Exception(f"Get ClickUp task failed: {limit_log_length(url)}, {limit_log_length(str(e))}")

    def _format_resource_details(self, resource_type: str, data: Any) -> str:
        """
        Format different types of ClickUp resources.
        Handles both dictionary and list data types.
        """
        # If data is None or empty, return an error message
        if not data:
            return "No data available for this resource."
            
        # If data is a list, use the first item
        if isinstance(data, list):
            if not data:  # Empty list
                return "No data available for this resource."
            data = data[0]  # Use the first item in the list
            
        # Now data should be a dictionary, but let's check to be sure
        if not isinstance(data, dict):
            return f"Unexpected data format: {type(data)}. Expected a dictionary or a list of dictionaries."
            
        if resource_type == 'task':
            # Safely access nested dictionary values
            status = data.get('status', {})
            status_text = status.get('status', 'N/A') if isinstance(status, dict) else 'N/A'
            
            priority = data.get('priority', {})
            priority_text = priority.get('priority', 'N/A') if isinstance(priority, dict) else 'N/A'
            
            # Safely handle lists
            assignees = data.get('assignees', [])
            assignee_text = ', '.join([assignee.get('username', 'N/A') for assignee in assignees]) if assignees else 'N/A'
            
            tags = data.get('tags', [])
            tag_text = ', '.join([tag.get('name', 'N/A') for tag in tags]) if tags else 'N/A'
            
            return f"""
            Task Details:
            Name: {data.get('name', 'N/A')}
            Status: {status_text}
            Priority: {priority_text}
            Due Date: {data.get('due_date', 'N/A')}
            Description: {data.get('description', 'N/A')}
            Assignees: {assignee_text}
            Tags: {tag_text}
            """
        elif resource_type == 'list':
            # Safely handle tasks list
            tasks = data.get('tasks', [])
            task_count = len(tasks) if isinstance(tasks, list) else 0
            
            return f"""
            List Details:
            Name: {data.get('name', 'N/A')}
            Content: {data.get('content', 'N/A')}
            Status: {data.get('status', 'N/A')}
            Priority: {data.get('priority', 'N/A')}
            Assignee: {data.get('assignee', 'N/A')}
            Task Count: {task_count}
            """
        elif resource_type == 'doc':
            # Safely access nested dictionary values
            user = data.get('user', {})
            username = user.get('username', 'N/A') if isinstance(user, dict) else 'N/A'
            
            return f"""
            Document Details:
            Title: {data.get('name', 'N/A')}
            Content: {data.get('content', 'N/A')}
            Last Updated: {data.get('date_updated', 'N/A')}
            Created By: {username}
            Status: {data.get('status', 'N/A')}
            """
        return "Unknown resource type."

    def _run(self, url: str) -> str:
        """Execute the tool's main functionality"""
        try:
            # Get task information
            api_url = self.construct_api_url(url)
            logger.debug(f"Constructed API URL: {limit_log_length(api_url)}")
            
            task_data = self.get_task_info(api_url)
            logger.debug(f"Retrieved data type: {type(task_data)}")
            
            # Determine the resource type based on the URL
            if 'task' in api_url:
                resource_type = 'task'
            elif 'docs' in api_url:
                resource_type = 'doc'
            else:
                resource_type = 'unknown'
                
            logger.debug(f"Resource type determined: {resource_type}")
            
            # Format and return the resource details
            return self._format_resource_details(resource_type, task_data)

        except ValueError as e:
            logger.error(f"URL parsing error: {limit_log_length(str(e))}")
            return f"Error: {limit_log_length(str(e))}"
        except Exception as e:
            logger.error(f"General error: {limit_log_length(str(e))}")
            return f"Error analyzing ClickUp resource: {limit_log_length(str(e))}"
