# DevOps Agent - AI-Powered Operational Assistant

A versatile Slack bot powered by CrewAI that helps automate and enhance various Operational tasks.

## Prerequisites

- Python 3.8+
- Slack Bot Token
- OpenAI API Key (for CrewAI functionality)
- Anthropic API Key (optional)
- GitHub Personal Access Token (for workflow analysis)
- ClickUp API Key (for ClickUp integration)

## Installation

1. Clone the repository
2. Create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Configuration

1. Copy the example configuration files:
   ```bash
   cp .env.example .env
   cp repos_token.txt.example repos_token.txt
   ```

2. Update the `.env` file with your values:
   ```
   SLACK_BOT_TOKEN=xoxb-your-token
   SLACK_APP_TOKEN=xapp-your-token
   ANTHROPIC_API_KEY=your-key
   OPENAI_API_KEY=your-key
   OPENAI_API_BASE=your-base-url
   OPENAI_MODEL_NAME=your-model
   GITHUB_TOKEN=your-github-token
   CLICKUP_API_KEY=your-clickup-api-key
   ```

3. Update the `repos_token.txt` file with repository names and their Coveralls tokens:
   ```
   repo-name token
   another-repo another-token
   ```

## Usage

To start the agent, run slack_bot.py using the virtual environment you created:

```bash
source venv/bin/activate  # On Windows: venv\Scripts\activate
python slack_bot.py
```

### Features

1. Weekly Reports Generation
2. Monthly Coverage Analysis
3. GitHub Workflow Analysis
   - Analyze workflow failures in pull requests
   - Get detailed failure information and logs
   - Receive targeted suggestions for fixes
4. ClickUp Integration
   - Analyze ClickUp tasks and documents
   - Extract and format task information from Sprint Goal documents
   - Process ClickUp URLs shared in Slack
   
Example commands:
```
@DevOpsAgent weekly report
@DevOpsAgent monthly report
@DevOpsAgent analyze https://github.com/your-org/your-repo/pull/123
@DevOpsAgent get https://app.clickup.com/t/team_id/task_id
@DevOpsAgent analyze https://app.clickup.com/team_id/v/dc/doc_id/view_id
```

### GitHub Workflow Analysis

The bot can analyze GitHub workflow failures by:
- Identifying specific failing jobs and steps
- Providing contextual suggestions based on failure type
- Checking dependencies and configurations
- Offering general troubleshooting recommendations

To use this feature:
1. Ensure your GITHUB_TOKEN is configured in .env
2. Share a GitHub pull request URL with the bot
3. Receive detailed analysis and suggestions

### ClickUp Integration

The bot can analyze ClickUp resources and provide insights:
- Extract information from ClickUp tasks
- Process Sprint Goal documents and extract task lists
- Format task information with status and assignees

To use this feature:
1. Ensure your CLICKUP_API_KEY is configured in .env
2. Share a ClickUp task or document URL with the bot
3. Receive formatted information and analysis

