import os
import dotenv
import re
import requests
import openai
from crewai import Agent, Task, Crew
from crewai.tools import BaseTool
from pydantic import BaseModel, Field
from typing import Type, Optional, Dict, Any
from base64 import b64decode
from Excel_report_builder import generate_file
from slack_service import slack_service

dotenv.load_dotenv()
TIMEOUT = int(os.getenv("TIMEOUT", "30"))

# Configure OpenAI
openai.api_key = os.getenv("OPENAI_API_KEY")
openai.api_base = os.getenv("OPENAI_API_BASE")

class SlackMessageSchema(BaseModel):
    channel_id: str = Field(..., description="The Slack channel ID to send the message to")
    message: str = Field(..., description="The message to send")
    file_should_send: bool = Field(default=False, description="Whether to send a file with the message")
    thread_ts: str = Field(default=None, description="The thread timestamp to reply to")

class GitHubAnalysisSchema(BaseModel):
    url: str = Field(..., description="The GitHub PR URL to analyze")
    fix_code: bool = Field(False, description="Whether to attempt to fix the code automatically")

class SlackMessageTool(BaseTool):
    name: str = "send_slack_message"
    description: str = "Send a message to a Slack channel"
    args_schema: Type[BaseModel] = SlackMessageSchema

    def _run(self, channel_id: str, message: str, file_should_send: bool = None, thread_ts: str = None) -> bool:
        try:
            if file_should_send:
                return slack_service.upload_file(
                    channel_id=channel_id,
                    file=generate_file(),
                    thread_ts=thread_ts
                )
            else:
                return slack_service.send_message(
                    channel_id=channel_id,
                    message=message,
                    mrkdwn=True,
                    thread_ts=thread_ts
                )
        except Exception as e:
            print(f"Error sending Slack message: {str(e)}")
            return False

    async def _arun(self, channel_id: str, message: str, file_should_send: bool = None, thread_ts: str = None) -> bool:
        raise NotImplementedError("Async version not implemented")

class GitHubWorkflowTool(BaseTool):
    name: str = "analyze_github_workflow"
    description: str = "Analyze GitHub workflow failures and suggest improvements"
    args_schema: Type[BaseModel] = GitHubAnalysisSchema

    def _extract_repo_info(self, url: str) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
        """Extract repository information from GitHub URL.
        Returns (owner, repo, pr_number, error_message)"""

        # Check if it's a workflow run URL
        workflow_pattern = r"https://github\.com/([^/]+)/([^/]+)/actions/runs/(\d+)"
        if re.match(workflow_pattern, url):
            return None, None, None, "Please provide a Pull Request URL instead of a workflow run URL. The URL should be in the format: https://github.com/owner/repo/pull/number"

        # Check if it's a PR URL
        pr_pattern = r"https://github\.com/([^/]+)/([^/]+)/pull/(\d+)"
        match = re.match(pr_pattern, url)
        if match:
            return match.groups()[0], match.groups()[1], match.groups()[2], None

        return None, None, None, "Invalid GitHub URL format. Please provide a Pull Request URL in the format: https://github.com/owner/repo/pull/number"

    def _get_job_logs(self, job: Dict[str, Any], headers: Dict[str, str]) -> str:
        """Fetch logs from job steps"""
        all_logs = []
        
        # First try to get logs from the job's log URL
        if "url" in job:
            job_url = f"{job['url']}/logs"
            print(f"\nDebug: Fetching job logs from: {job_url}")
            response = requests.get(job_url, headers=headers, timeout=TIMEOUT)
            if response.status_code == 200:
                all_logs.append(response.text)
        
        # Then try to get logs from each step
        for step in job.get("steps", []):
            if step.get("conclusion") != "success":
                step_logs = []
                
                # Try to get logs from step's log URL
                if "log_url" in step:
                    print(f"\nDebug: Fetching step logs from: {step['log_url']}")
                    try:
                        response = requests.get(step["log_url"], headers=headers, timeout=TIMEOUT)
                        if response.status_code == 200:
                            step_logs.append(f"Step '{step['name']}' logs:")
                            step_logs.append(response.text)
                    except Exception as e:
                        print(f"Debug: Error fetching step logs: {str(e)}")
                
                # If no logs from log_url, try to get output from step
                if not step_logs and "output" in step:
                    step_logs.append(f"Step '{step['name']}' output:")
                    step_logs.append(step["output"])
                
                if step_logs:
                    all_logs.extend(step_logs)
        
        return "\n".join(all_logs)

    def _analyze_with_ai(self, logs: str, files_content: Dict[str, str]) -> Dict[str, Any]:
        """Use OpenAI to analyze logs and suggest fixes"""
        # Extract error patterns and their context from logs
        error_patterns = []
        for line in logs.split('\n'):
            if any(pattern in line.lower() for pattern in ['error:', 'failure:', 'failed:', 'exception:']):
                error_patterns.append(line.strip())

        # Create a code context map
        code_context = {}
        for file_path, content in files_content.items():
            # Extract the relevant parts of the code around error lines
            lines = content.split('\n')
            for i, line in enumerate(lines):
                for error in error_patterns:
                    if any(term in line.lower() for term in error.lower().split()):
                        start = max(0, i - 10)  # 10 lines before
                        end = min(len(lines), i + 10)  # 10 lines after
                        code_context[file_path] = {
                            'error_line': i + 1,
                            'context': '\n'.join(lines[start:end]),
                            'full_content': content
                        }

        # Join error patterns with newline
        error_logs = '\n'.join(error_patterns[:10])  # Show first 10 error patterns

        prompt = f"""
        You are an expert software engineer analyzing GitHub Actions workflow failures. You have access to both the workflow logs and the source code. Provide a detailed analysis to help fix the failing tests.

        Workflow Logs with Errors:
        {error_logs}

        Source Code Context for Related Files:
        {str(code_context)[:4000]}

        Full Changed Files:
        {str(files_content)[:4000]}

        Provide a comprehensive analysis in this format:

        1. Root Cause Analysis:
           - Detailed explanation of why the workflow is failing
           - Map each error in the logs to specific code locations
           - Analyze code patterns and potential issues
           - Identify any dependency or environment-related problems

        2. Code Analysis:
           For each problematic file:
           a) File path and error location (line numbers)
           b) Code flow analysis explaining how the error occurs
           c) Related code dependencies and their impact
           d) Potential design issues or anti-patterns

        3. Suggested Fixes:
           For each issue:
           a) File path and exact line numbers that need changes
           b) Current code block with line numbers
           c) Suggested code block with line numbers
           d) Explanation of why this solution works
           e) Related files that need corresponding changes (with line numbers)
           f) Test files that need updates (with line numbers)

           Format each fix like this:
           File: [file path]
           Lines: [line numbers]
           Current Code (lines X-Y):
           ```
           [code block with line numbers]
           ```
           Suggested Fix:
           ```
           [code block with line numbers]
           ```
           Related Changes:
           - File: [related file path]
             Lines: [line numbers]
             Changes needed: [description]

        4. Implementation Guide:
           - Step-by-step guide to implement the fixes
           - Required dependency updates
           - Test cases to add or modify
           - Potential migration steps if needed
           - Deployment considerations

        5. Prevention Recommendations:
           - Code patterns to avoid
           - Suggested architectural improvements
           - Testing strategy enhancements
           - CI/CD pipeline improvements

        Be specific and detailed in your suggestions. Include complete code blocks, not just fragments. Consider dependencies, imports, and any configuration changes needed.
        """

        try:
            client = openai.OpenAI(
                api_key=os.getenv("OPENAI_API_KEY"),
                base_url=os.getenv("OPENAI_API_BASE")
            )
            response = client.chat.completions.create(
                model=os.getenv("OPENAI_MODEL_NAME", "gpt-4"),
                messages=[{"role": "user", "content": prompt}]
            )
            analysis = response.choices[0].message.content
            
            # Add a note about running tests locally
            analysis += "\n\nIMPORTANT: Before pushing these changes:"
            analysis += "\n1. Run the tests locally to verify the fix"
            analysis += "\n2. Check for any new linting issues"
            analysis += "\n3. Ensure all dependencies are up to date"
            analysis += "\n4. Consider adding tests to prevent regression"
            
            return {
                "analysis": analysis,
                "success": True
            }
        except Exception as e:
            return {
                "analysis": f"Error analyzing with AI: {str(e)}",
                "success": False
            }

    def _get_file_content(self, owner: str, repo: str, path: str, headers: Dict[str, str]) -> str:
        """Fetch file content from GitHub"""
        url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
        response = requests.get(url, headers=headers, timeout=TIMEOUT)
        if response.status_code == 200:
            content = response.json()
            return b64decode(content["content"]).decode()
        return ""

    def _run(self, url: str, fix_code: bool = False) -> str:
        try:
            owner, repo, pr_number, error_msg = self._extract_repo_info(url)
            if error_msg:
                return error_msg

            if not all([owner, repo, pr_number]):
                return "Invalid GitHub URL format. Please provide a Pull Request URL in the format: https://github.com/owner/repo/pull/number"

            github_token = os.getenv("GITHUB_TOKEN")
            if not github_token:
                return "GitHub token not configured. Please set the GITHUB_TOKEN environment variable."

            headers = {
                "Authorization": f"token {github_token}",
                "Accept": "application/vnd.github.v3+json"
            }

            # Get PR details first to get the head SHA
            pr_url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}"
            print(f"\nDebug: Accessing PR URL: {pr_url}")
            print(f"Debug: Using headers: {headers}")
            pr_response = requests.get(pr_url, headers=headers, timeout=TIMEOUT)
            print(f"Debug: Response status: {pr_response.status_code}")
            if pr_response.status_code != 200:
                print(f"Debug: Response body: {pr_response.text}")
            
            if pr_response.status_code == 401:
                return "Authentication failed. Please verify that the GitHub token has the necessary permissions (repo and workflow scopes)."
            elif pr_response.status_code == 404:
                return "Pull request not found. Please verify the URL is correct and you have access to the repository."
            elif pr_response.status_code != 200:
                return f"Failed to fetch PR data. Status code: {pr_response.status_code}. Please verify the repository permissions and try again."
                
            pr_data = pr_response.json()
            head_sha = pr_data["head"]["sha"]
            
            # Get workflow runs for the PR using the head SHA
            api_url = f"https://api.github.com/repos/{owner}/{repo}/actions/runs"
            params = {"head_sha": head_sha}
            response = requests.get(api_url, headers=headers, params=params, timeout=TIMEOUT)
            print(f"\nDebug: Fetching workflow runs. Status: {response.status_code}")
            
            if response.status_code == 401:
                return "Authentication failed. Please verify that the GitHub token has the necessary permissions (repo and workflow scopes)."
            elif response.status_code == 404:
                return "Repository not found. Please verify the URL is correct and you have access to the repository."
            elif response.status_code != 200:
                return f"Failed to fetch workflow data. Status code: {response.status_code}. Please verify permissions and try again."

            workflow_data = response.json()
            if not workflow_data.get("workflow_runs"):
                return "No workflow runs found for this PR."

            # Get all recent workflow runs for this PR
            workflow_runs = workflow_data["workflow_runs"]
            print(f"\nDebug: Found {len(workflow_runs)} workflow runs")
            
            # First summarize all workflow statuses
            workflow_summary = []
            for run in workflow_runs:
                status = run.get("conclusion", "unknown")
                name = run.get("name", "Unknown workflow")
                if status not in ["success", None]:
                    workflow_summary.append(f"- {name}: {status}")
            
            if workflow_summary:
                analysis = [
                    "\nWorkflow Status Summary:",
                    *workflow_summary,
                    "\nDetailed Analysis:"
                ]
            else:
                analysis = []
            
            # Check all recent runs
            all_jobs_data = []
            for run in workflow_runs[:3]:  # Check last 3 runs
                run_id = run["id"]
                run_status = run["conclusion"]
                workflow_name = run["name"]
                workflow_html_url = run.get("html_url", "")
                print(f"\nDebug: Analyzing run {run_id} ({workflow_name}) - Status: {run_status}")
                
                if run_status not in ["success", None]:
                    analysis.append(f"\nWorkflow '{workflow_name}' failed (Status: {run_status})")
                    if workflow_html_url:
                        analysis.append(f"View details: {workflow_html_url}")
                
                # Get jobs for this run
                jobs_url = run["jobs_url"]
                jobs_response = requests.get(jobs_url, headers=headers, timeout=TIMEOUT)
                print(f"Debug: Fetching jobs from: {jobs_url}")
                print(f"Debug: Jobs response status: {jobs_response.status_code}")
                
                if jobs_response.status_code == 200:
                    jobs = jobs_response.json()
                    all_jobs_data.extend(jobs.get("jobs", []))
                    
            if not all_jobs_data:
                return "Could not find any job data in the workflow runs."
                
            print(f"\nDebug: Total jobs found across runs: {len(all_jobs_data)}")
            
            # Get check runs for the PR
            check_runs_url = f"https://api.github.com/repos/{owner}/{repo}/commits/{head_sha}/check-runs"
            check_response = requests.get(check_runs_url, headers=headers, timeout=TIMEOUT)
            print(f"\nDebug: Fetching check runs from: {check_runs_url}")
            print(f"Debug: Check runs response status: {check_response.status_code}")
            
            if check_response.status_code == 200:
                check_data = check_response.json()
                check_runs = check_data.get("check_runs", [])
                print(f"Debug: Found {len(check_runs)} check runs")
                
                # Add check runs to jobs data if they're not already included
                for check in check_runs:
                    if check["status"] == "completed" and check["conclusion"] != "success":
                        all_jobs_data.append({
                            "name": check["name"],
                            "conclusion": check["conclusion"],
                            "url": check["url"],
                            "steps": []
                        })
            
            # Analyze all jobs
            all_logs = []
            has_failures = False
            
            print("\nDebug: Processing all jobs for logs and analysis")
            for job in all_jobs_data:
                job_name = job.get("name", "Unknown Job")
                job_status = job.get("conclusion")
                print(f"Debug: Job '{job_name}' status: {job_status}")
                
                if job_status not in ["success", None]:
                    has_failures = True
                    analysis.append(f"\nJob '{job_name}' failed (Status: {job_status}):")
                    
                    # Get job logs
                    job_logs = self._get_job_logs(job, headers)
                    if job_logs:
                        all_logs.append(f"\nLogs for job '{job_name}':")
                        all_logs.append(job_logs)
                        
                        # Enhanced test and error analysis
                        test_lines = []
                        error_lines = []
                        in_test_block = False
                        current_test = None
                        failed_tests = {}  # Dictionary to store test failures with their context
                        passed_tests = []
                        error_context = {}  # Store error context for better analysis
                        
                        lines = job_logs.split('\n')
                        for i, line in enumerate(lines):
                            line = line.strip()
                            if not line:
                                continue

                            # Track test blocks with enhanced context
                            if line.startswith("=== RUN"):
                                in_test_block = True
                                current_test = line.replace("=== RUN", "").strip()
                                # Get test context (next few lines)
                                test_context = '\n'.join(lines[i+1:i+5])
                            elif line.startswith("--- FAIL:"):
                                test_name = line.replace("--- FAIL:", "").split()[0].strip()
                                # Get failure context (previous and next few lines)
                                context_start = max(0, i-5)
                                context_end = min(len(lines), i+5)
                                failure_context = '\n'.join(lines[context_start:context_end])
                                failed_tests[test_name] = {
                                    'context': failure_context,
                                    'line_number': i + 1
                                }
                                in_test_block = False
                            elif line.startswith("--- PASS:"):
                                test_name = line.replace("--- PASS:", "").split()[0].strip()
                                passed_tests.append(test_name)
                                in_test_block = False
                            elif in_test_block and any(pattern in line.lower() for pattern in
                                ["error:", "failed:", "panic:", "fatal:", "exception:", "undefined:", "null pointer"]):
                                if current_test:
                                    test_lines.append(f"\n:x: Test Failed: {current_test}")
                                    test_lines.append(f"    Error: {line}")
                                    # Get error context
                                    context_start = max(0, i-5)
                                    context_end = min(len(lines), i+5)
                                    error_context[line] = {
                                        'test': current_test,
                                        'context': '\n'.join(lines[context_start:context_end]),
                                        'line_number': i + 1
                                    }
                                error_lines.append(line)
                            elif any(pattern in line.lower() for pattern in
                                ["error:", "failed:", "panic:", "fatal:", "exception:", "undefined:", "null pointer"]):
                                error_lines.append(line)
                                # Get error context
                                context_start = max(0, i-5)
                                context_end = min(len(lines), i+5)
                                error_context[line] = {
                                    'context': '\n'.join(lines[context_start:context_end]),
                                    'line_number': i + 1
                                }
                        
                        # Add test summary
                        if failed_tests or passed_tests:
                            analysis.append(f"\n  Test Summary for {job_name}:")
                            if failed_tests:
                                analysis.append("  :x: Failed Tests:")
                                for test in failed_tests:
                                    analysis.append(f"    • {test}")
                            if passed_tests:
                                analysis.append("  :white_check_mark: Passed Tests:")
                                for test in passed_tests:
                                    analysis.append(f"    • {test}")
                        
                        # Add detailed test results
                        if test_lines:
                            analysis.append("\n  Detailed Test Results:")
                            analysis.extend(test_lines)
                        
                        # Add error details
                        if error_lines:
                            analysis.append("\n  Error Details:")
                            for error in error_lines[:5]:  # Show first 5 error messages
                                analysis.append(f"    {error.strip()}")
                            
                            # Provide specific suggestions based on error type
                            if any('syntax error' in line.lower() for line in error_lines):
                                analysis.append("\n  :bulb: Suggestion: Fix syntax errors in the code")
                            elif any('dependency' in line.lower() for line in error_lines):
                                analysis.append("\n  :bulb: Suggestion: Update or install missing dependencies")
                            elif any('test failed' in line.lower() for line in error_lines):
                                analysis.append("\n  :bulb: Suggestion: Review failing test cases and update test expectations")

            if not has_failures and not workflow_summary:
                print("Debug: No failed jobs or workflows found")
                return "All workflows are passing successfully."
            
            if not has_failures and workflow_summary:
                return f"""Workflow failures detected:

Unable to fetch detailed logs. This might indicate:
1. The workflows are still in progress
2. The logs have expired (logs are typically available for 7 days)
3. There are permission issues accessing the logs
4. The workflow configuration needs to be checked

Please check the workflow details directly on GitHub for more information."""

            # Get PR changes and their content
            pr_files_url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/files"
            print(f"\nDebug: Fetching PR files from: {pr_files_url}")
            files_response = requests.get(pr_files_url, headers=headers, timeout=TIMEOUT)
            print(f"Debug: Files response status: {files_response.status_code}")
            
            files_content = {}
            if files_response.status_code == 200:
                files_data = files_response.json()
                analysis.append("\nChanged files:")
                for file in files_data:
                    filename = file["filename"]
                    analysis.append(f"- {filename}")
                    # Get file content
                    print(f"Debug: Fetching content for: {filename}")
                    content = self._get_file_content(owner, repo, filename, headers)
                    if content:
                        files_content[filename] = content
                        print(f"Debug: Successfully got content for: {filename}")

            workflow_logs = "\n".join(all_logs)
            
            # Use AI to analyze logs and suggest fixes
            if workflow_logs:
                print("\nDebug: Got workflow logs, sending to AI for analysis")
                print(f"Debug: Log content preview: {workflow_logs[:200]}...")  # Preview first 200 chars
                ai_analysis = self._analyze_with_ai(workflow_logs, files_content)
                if ai_analysis["success"]:
                    analysis.append("\n:mag: AI Analysis:")

                    # Format the analysis with clear section headers and file references
                    ai_result = ai_analysis["analysis"]

                    # Add file links for GitHub
                    for file_path in files_content.keys():
                        if file_path in ai_result:
                            file_link = f"https://github.com/{owner}/{repo}/blob/{head_sha}/{file_path}"
                            ai_result = ai_result.replace(
                                f"File: {file_path}",
                                f"File: {file_path}\nView: {file_link}"
                            )

                    # Add the formatted analysis
                    analysis.append(ai_result)

                    # Add a summary of files that need changes
                    affected_files = set()
                    for file_path in files_content.keys():
                        if file_path in ai_result:
                            affected_files.add(file_path)

                    if affected_files:
                        analysis.append("\n:file_folder: Files Requiring Changes:")
                        for file_path in sorted(affected_files):
                            analysis.append(f"• {file_path}")
                else:
                    print(f"\nDebug: AI analysis failed: {ai_analysis['analysis']}")
            else:
                print("\nDebug: No workflow logs available for analysis")
                analysis.append("\nNote: Could not retrieve detailed workflow logs. They may have expired or been deleted.")

            return "\n".join([
                f"Analysis for PR #{pr_number} in {owner}/{repo}:",
                "Workflow Status: Failed",
                *analysis,
                "\nRecommended Actions:",
                "1. Review the specific error messages above",
                "2. Check the changed files for potential issues",
                "3. Ensure all tests are passing locally before pushing",
                "4. Verify compatibility with the latest main branch"
            ])

        except Exception as e:
            error_msg = str(e)
            if "401" in error_msg:
                return "Authentication failed. Please verify that:\n1. The GitHub token is valid\n2. The token has the necessary permissions (repo and workflow scopes)\n3. The token has not expired"
            elif "404" in error_msg:
                return "Resource not found. Please verify that:\n1. The repository exists\n2. You have access to the repository\n3. The pull request number is correct"
            else:
                return f"Error analyzing workflow: {error_msg}\nPlease check:\n1. Your network connection\n2. GitHub API status\n3. Repository permissions"

    async def _arun(self, url: str) -> str:
        raise NotImplementedError("Async version not implemented")
