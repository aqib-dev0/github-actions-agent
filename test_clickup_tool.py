import unittest
import os
import requests
from clickup_tool import ClickUpTool

class TestClickUpTool(unittest.TestCase):

    def setUp(self):
        """Set up the ClickUpTool instance for testing."""
        self.tool = ClickUpTool()
        self.api_key = os.getenv("CLICKUP_API_KEY")
        if not self.api_key:
            raise ValueError("CLICKUP_API_KEY not found in environment variables")

    def test_construct_api_url_task(self):
        """Test constructing API URL for a ClickUp task."""
        url = "https://app.clickup.com/t/20696747/CICD-1261"  # Replace with a valid task URL
        expected_url = "https://api.clickup.com/api/v2/task/CICD-1261?team_id=20696747&custom_task_ids=true"
        api_url = self.tool.construct_api_url(url)
        self.assertEqual(api_url, expected_url)

    def test_construct_api_url_document(self):
        """Test constructing API URL for a ClickUp document view."""
        url = "https://app.clickup.com/20696747/v/dc/kqknb-962555/kqknb-521815"  # Replace with a valid document URL
        expected_url = "https://api.clickup.com/api/v3/workspaces/20696747/docs/kqknb-962555/pages?max_page_depth=-1&content_format=text%2Fmd"
        api_url = self.tool.construct_api_url(url)
        self.assertEqual(api_url, expected_url)

    def test_construct_api_url_invalid(self):
        """Test constructing API URL with an unsupported ClickUp URL."""
        url = "https://app.clickup.com/invalid/url"
        with self.assertRaises(ValueError) as context:
            self.tool.construct_api_url(url)
        self.assertEqual(str(context.exception), "Unsupported ClickUp URL")

    def test_get_task_info_success(self):
        """Test getting task information successfully."""
        url = "https://app.clickup.com/t/20696747/CICD-1261"  # Replace with a valid task URL
        url = self.tool.construct_api_url(url)
        task_info = self.tool.get_task_info(url)

        self.assertIn("name", task_info)
        self.assertIn("status", task_info)
        self.assertIn("assignees", task_info)

    def test_get_task_info_failure(self):
        """Test getting task information with an error."""
        url = "https://app.clickup.com/t/20696747/INVALID_TASK_ID"  # Use an invalid task ID
        url = self.tool.construct_api_url(url)
        with self.assertRaises(requests.exceptions.HTTPError) as context:
            self.tool.get_task_info(url)
        self.assertIn("401", str(context.exception))

    def test_get_doc_info_success(self):
        """Test getting doc information successfully."""
        url = "https://app.clickup.com/20696747/v/dc/kqknb-962555/kqknb-521815"  # Replace with a valid task URL
        url = self.tool.construct_api_url(url)
        task_info = self.tool.get_task_info(url)
        self.assertEqual(task_info[0]["id"], "kqknb-521815")
        self.assertEqual(task_info[0]["doc_id"], "kqknb-962555")
        self.assertEqual(task_info[0]["name"], "Sprint Goals")

    def test_integration_task_info_and_format(self):
        """Test integration between get_task_info and _format_resource_details for tasks."""
        url = "https://app.clickup.com/t/20696747/CICD-1261"  # Replace with a valid task URL
        url = self.tool.construct_api_url(url)
        task_info = self.tool.get_task_info(url)

        # Format the task info
        formatted_output = self.tool._format_resource_details('task', task_info)

        # Verify the formatted output contains expected information
        self.assertIn(task_info.get('name', 'N/A'), formatted_output)
        self.assertIn(task_info.get('status', {}).get('status', 'N/A'), formatted_output)
        if task_info.get('description'):
            self.assertIn(task_info.get('description'), formatted_output)

        # Verify the structure of the output
        self.assertIn("Name:", formatted_output)
        self.assertIn("Status:", formatted_output)

    def test_integration_doc_info_and_format(self):
        """Test integration between get_task_info and _format_resource_details for documents."""
        url = "https://app.clickup.com/20696747/v/dc/kqknb-962555/kqknb-521815"  # Replace with a valid doc URL
        url = self.tool.construct_api_url(url)
        doc_info = self.tool.get_task_info(url)

        # Format the first document in the list
        formatted_output = self.tool._format_resource_details('doc', doc_info[0])

        # Verify the formatted output contains expected information
        self.assertIn(doc_info[0].get('name', 'N/A'), formatted_output)

        # Verify the structure of the output
        self.assertIn("Document Details:", formatted_output)
        self.assertIn("Title:", formatted_output)

    def test_format_resource_details_task(self):
        """Test formatting task details."""
        task_data = {
            "name": "Test Task",
            "status": {"status": "In Progress"},
            "priority": {"priority": "High"},
            "due_date": "2023-12-31",
            "description": "This is a test task.",
            "assignees": [{"username": "test_user"}],
            "tags": [{"name": "urgent"}]
        }
        expected_output = """
            Task Details:
            Name: Test Task
            Status: In Progress
            Priority: High
            Due Date: 2023-12-31
            Description: This is a test task.
            Assignees: test_user
            Tags: urgent
            """.strip()
        formatted_output = self.tool._format_resource_details('task', task_data)
        self.assertEqual(formatted_output.strip(), expected_output)

    def test_format_resource_details_doc(self):
        """Test formatting document details."""
        doc_data = {
            "name": "Test Document",
            "content": "This is a test document.",
            "date_updated": "2023-12-31",
            "user": {"username": "doc_creator"},
            "status": "Published"
        }
        expected_output = """
            Document Details:
            Title: Test Document
            Content: This is a test document.
            Last Updated: 2023-12-31
            Created By: doc_creator
            Status: Published
            """.strip()
        formatted_output = self.tool._format_resource_details('doc', doc_data)
        self.assertEqual(formatted_output.strip(), expected_output)

    def test_end_to_end_task(self):
        """Test the complete workflow from URL to formatted output for a task."""
        url = "https://app.clickup.com/t/20696747/CICD-1261"  # Replace with a valid task URL

        # Call the _run method which should get the task info and format it
        result = self.tool._run(url)

        # Verify the result contains expected task information
        self.assertIn("Name:", result)
        self.assertIn("Status:", result)

    def test_end_to_end_doc(self):
        """Test the complete workflow from URL to formatted output for a document."""
        url = "https://app.clickup.com/20696747/v/dc/kqknb-962555/kqknb-521815"  # Replace with a valid doc URL

        # Call the _run method which should get the doc info and format it
        result = self.tool._run(url)

        # Verify the result contains expected document information
        self.assertIn("Title:", result)

if __name__ == '__main__':
    unittest.main()
