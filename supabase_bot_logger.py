import os
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# Supabase configuration
SUPABASE_API_KEY = os.getenv("SUPABASE_API_KEY")
SUPABASE_EMAIL = os.getenv("SUPABASE_EMAIL")
SUPABASE_PASSWORD = os.getenv("SUPABASE_PASSWORD")
SUPABASE_URL = os.getenv("SUPABASE_URL")
TIMEOUT = int(os.getenv("TIMEOUT", "30"))
class SupabaseLogger:
    def __init__(self, logger):
        self.api_key = SUPABASE_API_KEY
        self.email = SUPABASE_EMAIL
        self.password = SUPABASE_PASSWORD
        self.base_url = SUPABASE_URL
        self.auth_token = None
        self.auth_expiry = None
        self.bot_registered = False
        self.logger = logger
        self.ai_bot_id = "DevOps_Agent"

    def authenticate(self):
        """Authenticate with Supabase and get JWT token"""
        url = f"{self.base_url}/auth/v1/token?grant_type=password"
        headers = {
            "Content-Type": "application/json",
            "apikey": self.api_key
        }
        payload = {
            "email": self.email,
            "password": self.password
        }
        
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            auth_data = response.json()
            self.auth_token = auth_data.get("access_token")
            # Set expiry time (typically 1 hour)
            self.auth_expiry = datetime.now().timestamp() + 3600
            self.logger.info("Successfully authenticated with Supabase")
            return True
        except Exception as e:
            self.logger.error(f"Authentication failed: {str(e)}")
            return False

    def ensure_authenticated(self):
        """Ensure we have a valid authentication token"""
        current_time = datetime.now().timestamp()
        if not self.auth_token or not self.auth_expiry or current_time >= self.auth_expiry:
            return self.authenticate()
        return True

    def register_bot(self):
        """Register the bot in the ai_bot_info table (one-time setup)"""
        if self.bot_registered:
            return True
            
        if not self.ensure_authenticated():
            return False
            
        url = f"{self.base_url}/rest/v1/ai_bot_info"
        headers = {
            "Content-Type": "application/json",
            "apikey": self.api_key,
            "Authorization": f"Bearer {self.auth_token}"
        }
        payload = {
            "ai_bot_id": self.ai_bot_id,
            "name": "DevOps Agent",
            "type": "Generative AI",
            "title": "DevOps Agent. Your AI assistant for developer operations.",
            "reporting_manager": "your_manager@example.com",  # Update with actual manager
            "expertise": "Answering questions and automating developer operations workflows.",
            "responsibilities": "Process user queries and provide answers using RAG",
            "channel": "#devops_agent",  # Update with actual channel
            "team_department": "Developer Operations",
            "website": "https://your-agent-url.example.com/",
            "slack_handle": "@devopsagent"
        }
        
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=TIMEOUT)
            if response.status_code == 409:  # Already exists
                self.bot_registered = True
                self.logger.info("Bot already registered in Supabase")
                return True
                
            response.raise_for_status()
            self.bot_registered = True
            self.logger.info("Successfully registered bot in Supabase")
            return True
        except Exception as e:
            self.logger.error(f"Failed to register bot: {str(e)}")
            return False

    def log_interaction(self, user_id, channel_id, thread_id, user_message, response_text, duration, environment="PROD"):
        """Log bot interaction to Supabase"""
        if not self.ensure_authenticated():
            self.logger.error("Failed to log interaction - authentication failed")
            return False
            
        # Ensure bot is registered
        if not self.bot_registered:
            self.register_bot()
            
        request_timestamp = datetime.now().isoformat() + "Z"
        response_timestamp = datetime.now().isoformat() + "Z"
        
        url = f"{self.base_url}/rest/v1/ai_bot_logs"
        headers = {
            "Content-Type": "application/json",
            "apikey": self.api_key,
            "Authorization": f"Bearer {self.auth_token}"
        }
        
        # Create payload based on ai_bot_logs table schema
        payload = {
            "created_at": response_timestamp,
            "request_timestamp": request_timestamp,
            "response_timestamp": response_timestamp,
            "ai_bot_id": self.ai_bot_id,
            "type_of_bot": "rag_assistant",
            "user_id": user_id,
            "channel_id": channel_id,
            "thread_id": thread_id,
            "user_message": user_message,
            "input_attachments": {
                "type": "text",
                "content": []
            },
            "system_prompt": "Answer questions using RAG",
            "chat_history_length": 1,  # Could be updated based on actual history length
            "response_text": response_text[:1000] if response_text else "",  # Truncate if too long
            "duration": duration,
            "output_attachments": {
                "type": "text",
                "content": []
            },
            "environment": environment
        }
        
        self.logger.info(f"Logging interaction: {payload}")
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=TIMEOUT)
            response.raise_for_status()
            self.logger.info(f"Successfully logged interaction for user {user_id}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to log interaction: {str(e)}")
            return False
