from slack_bolt.adapter.socket_mode import SocketModeHandler
from dotenv import load_dotenv
import os
import re
from crewAIagent import GitHubWorkflowTool, SlackMessageTool
from crew_sprint import create_sprint_crew
from crewai import Agent, Task, Crew
import warnings
import opentelemetry
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, ConsoleSpanExporter
import logging
import time
import json
import requests
from datetime import datetime
from prometheus_client import Counter, Gauge, start_http_server
from slack_service import app, slack_service
from supabase_bot_logger import SupabaseLogger

# Configure OpenTelemetry properly
warnings.filterwarnings("ignore", category=Warning)
if not opentelemetry.trace.get_tracer_provider():
    tracer_provider = TracerProvider()
    tracer_provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    opentelemetry.trace.set_tracer_provider(tracer_provider)

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("slack_bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Set up Prometheus metrics
EXECUTIONS_COUNTER = Counter('bot_executions_total', 'Total number of bot executions')
MONTHLY_USERS = Gauge('monthly_active_users', 'Number of monthly active users')
TOTAL_USERS = Gauge('total_users', 'Total number of users to date')

# Load environment variables
load_dotenv(verbose=True, override=True)
SLACK_APP_TOKEN = os.getenv("SLACK_APP_TOKEN")
TIMEOUT = int(os.getenv("TIMEOUT", "30"))

# User tracking for Prometheus
user_set = set()
monthly_user_set = set()
last_month_reset = datetime.now().month
start_http_server(8000)

# Initialize Supabase logger
supabase_logger = SupabaseLogger(logger)

weekly_report_template = """
What was done in the past Week: No update
What's planned for this week: No update
Have you reviewed the payment details?: No update
SOSA Form Updated: No update
Other updates: No update
Coveralls: https://coveralls.io/github/regentmarkets
"""

def create_agent():
    """Create a new agent instance for each request to avoid TracerProvider conflicts"""
    return Agent(
        role='Operations Assistant',
        goal='Analyze GitHub workflows and handle operational tasks',
        backstory='Expert in analyzing GitHub Actions workflows, generating reports, and providing operational support.',
        verbose=False,
        tools=[GitHubWorkflowTool(), SlackMessageTool()]
    )

def format_github_analysis(result_str: str) -> str:
    """Format GitHub workflow analysis for Slack"""
    # Convert the CrewOutput to string
    result_str = str(result_str)

    # Check for error messages about invalid URLs
    if "Please provide a Pull Request URL" in result_str or "Invalid GitHub URL format" in result_str:
        return f":warning: {result_str}"

    # Format workflow analysis
    lines = result_str.split('\n')
    formatted_lines = []
    
    # Track workflow statuses
    workflow_statuses = {
        "success": [],
        "failure": [],
        "other": []
    }
    
    # Process lines and categorize workflows
    current_workflow = None
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # Track workflow status
        if "Workflow '" in line and "' failed" in line:
            current_workflow = {
                "name": line.split("'")[1],
                "status": "failure"
            }
            workflow_statuses["failure"].append(current_workflow)
        elif "Workflow '" in line and "' succeeded" in line:
            current_workflow = {
                "name": line.split("'")[1],
                "status": "success"
            }
            workflow_statuses["success"].append(current_workflow)
            
        # Format the line
        formatted_line = line
        if "failed" in line.lower() or "failure" in line.lower():
            formatted_line = ":x: " + line
        elif "success" in line.lower():
            formatted_line = ":white_check_mark: " + line
        elif "warning" in line.lower():
            formatted_line = ":warning: " + line
        elif "error" in line.lower():
            formatted_line = ":rotating_light: " + line
            
        # Format code blocks
        if line.startswith("```"):
            formatted_line = "```" + line.replace("```", "")
            
        formatted_lines.append(formatted_line)
    
    # Create summary section
    summary_lines = [":mag: GitHub Workflow Analysis"]
    if "pull request" in str(result_str).lower():
        pr_match = re.search(r'PR #(\d+)', str(result_str))
        if pr_match:
            summary_lines[0] += f" for PR #{pr_match.group(1)}"
    
    summary_lines.append("\n*Workflow Status Summary:*")
    if workflow_statuses["success"]:
        summary_lines.append(":white_check_mark: *Passing Workflows:*")
        for wf in workflow_statuses["success"]:
            summary_lines.append(f"• {wf['name']}")
    
    if workflow_statuses["failure"]:
        summary_lines.append("\n:x: *Failing Workflows:*")
        for wf in workflow_statuses["failure"]:
            summary_lines.append(f"• {wf['name']}")
            
    summary_lines.append("\n*Detailed Analysis:*")
    
    # Combine summary with detailed analysis
    return "\n".join(summary_lines + formatted_lines)

def update_metrics(user_id):
    """Update metrics for user activity - both Prometheus and Supabase"""
    global monthly_user_set, user_set, last_month_reset
    
    # Check if we need to reset monthly users (new month)
    current_month = datetime.now().month
    if current_month != last_month_reset:
        monthly_user_set = set()
        last_month_reset = current_month
        logger.info(f"Reset monthly users tracking for new month: {current_month}")
    
    # Track execution with Prometheus
    EXECUTIONS_COUNTER.inc()
    
    # Track unique users
    is_new_user = False
    if user_id not in user_set:
        user_set.add(user_id)
        is_new_user = True
        TOTAL_USERS.set(len(user_set))
        logger.info(f"New user: {user_id}, Total users: {len(user_set)}")
    
    # Track monthly users
    is_new_monthly_user = False
    if user_id not in monthly_user_set:
        monthly_user_set.add(user_id)
        is_new_monthly_user = True
        MONTHLY_USERS.set(len(monthly_user_set))
        logger.info(f"New monthly user: {user_id}, Monthly users: {len(monthly_user_set)}")
        
    # Return metrics info for Supabase logging
    return {
        "total_users": len(user_set),
        "monthly_users": len(monthly_user_set),
        "is_new_user": is_new_user,
        "is_new_monthly_user": is_new_monthly_user
    }

def create_crew(query, channel_id, thread_ts):
    """Create a new Crew for GitHub PR analysis, weekly reports, or other queries."""
    # Create new agent instance for each request
    agent = create_agent()
    
    # Check if the query contains any GitHub URL
    github_url_match = re.search(r'https://github\.com/[^/]+/[^/]+/(?:pull/\d+|actions/runs/\d+)', query)
    
    if github_url_match:
        # GitHub workflow analysis task
        task = Task(
            description=f"""
            Analyze the GitHub workflow for this URL: {github_url_match.group(0)}
            
            1. Use the GitHubWorkflowTool to analyze the workflow failures
            2. Format the response for Slack:
               - Use code blocks for logs and code snippets
               - Use bullet points for lists
               - Break up long messages into multiple Slack messages if needed
            3. Send the analysis results to:
               - Channel ID: {channel_id}
               - Thread TS: {thread_ts}
            
            Make the response clear and actionable for the user.
            """,
            expected_output='',
            agent=agent
        )
    else:
        # Other tasks (reports, general queries)
        task = Task(
            description=f"""
            Based on this context do one of the following based on what context is asking:
            {query}

            1. If the query is about a weekly report:
            - Respond to same thread thread_ts={thread_ts} with the weekly report template: {weekly_report_template}
            
            2. If the query is about a monthly report:
            - Send the coverage analysis file via Slack to the same thread thread_ts={thread_ts}
            
            3. For any other queries in the same thread thread_ts={thread_ts}:
            - Provide a helpful and professional response 
            - Answer any questions about processes, workflows, or general inquiries
            - Maintain a friendly and human-like tone
            - Offer assistance or clarification if needed
            Channel ID: {channel_id}
            """,
            expected_output='',
            agent=agent
        )

    crew = Crew(
        agents=[agent],
        tasks=[task],
        verbose=False
    )
    return crew

@app.event("app_mention")
def handle_mention(event, say, client):
    channel_id = event.get("channel")
    text = event.get("text")
    user_id = event.get("user")
    thread_ts = event.get("thread_ts", event.get("ts"))

    # Update both Prometheus metrics and prepare Supabase metrics data
    metrics = update_metrics(user_id)

    # Remove the bot mention and clean up Slack-formatted URLs from the text
    query = re.sub(r'<@[A-Z0-9]+>', '', text)
    # Convert Slack URL format <https://example.com|text> to just the URL
    query = re.sub(r'<(https?://[^|>]+)[^>]*>', r'\1', query).strip()

    # Check if we've already processed this message
    message_id = event.get("ts")
    if hasattr(handle_mention, 'last_processed') and handle_mention.last_processed == message_id:
        return
    handle_mention.last_processed = message_id

    # Print detailed log information
    logger.info(f"Received message from user {user_id} in channel {channel_id}")
    logger.info(f"Query: {query}")

    # Send initial "thinking" message
    thinking_message = say("Thinking...", thread_ts=thread_ts)

    task_type = 'help'
    if re.search(r'https://app\.clickup\.com/\w+', query):
        task_type = 'clickup'
        crew = create_sprint_crew(query, channel_id, thread_ts)
    else:
        crew = create_crew(query, channel_id, thread_ts)
    
    start_time = time.time()
    try:
        # Run the task
        result = crew.kickoff()
        result_str = str(result)
        execution_time = time.time() - start_time
        logger.info(f"Task completed in {execution_time:.2f} seconds")

        if re.search(r'https://github\.com/[^/]+/[^/]+/pull/\d+', query):
            # Format GitHub analysis for Slack
            formatted_result = format_github_analysis(result_str)

            # Send the formatted result in chunks
            slack_service.send_chunked_message(
                channel_id=channel_id,
                text=formatted_result,
                thread_ts=thread_ts
            )
        
        # Log the interaction to Supabase
        supabase_logger.log_interaction(
            user_id=user_id,
            channel_id=channel_id,
            thread_id=thread_ts,
            user_message=query,
            response_text=result_str,
            duration=execution_time
        )
        
        # Delete the "thinking" message
        slack_service.delete_message(
            channel_id=channel_id,
            ts=thinking_message['ts']
        )
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error processing request: {error_msg}", exc_info=True)
        
        # Log the error to Supabase
        supabase_logger.log_interaction(
            user_id=user_id,
            channel_id=channel_id,
            thread_id=thread_ts,
            user_message=query,
            response_text=f"Error: {error_msg}",
            duration=time.time() - start_time
        )
        
        # Update the "thinking" message with the error
        slack_service.update_message(
            channel_id=channel_id,
            ts=thinking_message['ts'],
            text=f"Sorry, I encountered an error: {error_msg}"
        )
 
@app.event("message")
def handle_message_events(body, logger):
    logger.info(body)

# Start the bot
if __name__ == "__main__":
    # Initialize the Supabase logger and register the bot
    if supabase_logger.authenticate():
        supabase_logger.register_bot()
    else:
        logger.error("Failed to authenticate with Supabase. Check credentials.")
    
    logger.info("Starting Slack bot with Prometheus metrics on port 8000 and Supabase logging")
    handler = SocketModeHandler(app, SLACK_APP_TOKEN)
    handler.start()
