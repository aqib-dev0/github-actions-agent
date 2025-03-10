from slack_bolt import App
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv(verbose=True, override=True)

# Initialize Slack app
app = App(token=os.getenv("SLACK_BOT_TOKEN"))

class SlackService:
    def __init__(self, app):
        self.app = app
    
    def send_message(self, channel_id, message, thread_ts=None, mrkdwn=True):
        """Send a message to a Slack channel"""
        return self.app.client.chat_postMessage(
            channel=channel_id,
            text=message,
            thread_ts=thread_ts,
            mrkdwn=mrkdwn
        )
    
    def upload_file(self, channel_id, file, thread_ts=None, filename="coverage_analysis.xlsx", title="Coverage Analysis Report"):
        """Upload a file to a Slack channel"""
        return self.app.client.files_upload_v2(
            channel=channel_id,
            file=file,
            initial_comment="Here's the detailed report:",
            filename=filename,
            title=title,
            thread_ts=thread_ts
        )
    
    def delete_message(self, channel_id, ts):
        """Delete a message from a Slack channel"""
        return self.app.client.chat_delete(
            channel=channel_id,
            ts=ts
        )
    
    def update_message(self, channel_id, ts, text):
        """Update a message in a Slack channel"""
        return self.app.client.chat_update(
            channel=channel_id,
            ts=ts,
            text=text
        )

    def send_chunked_message(self, channel_id, text, thread_ts=None, max_length=3000):
        """Send a long message in chunks to avoid Slack's message length limit"""
        chunks = []
        current_chunk = []
        current_length = 0
        
        for line in text.split('\n'):
            line_length = len(line) + 1  # +1 for newline
            if current_length + line_length > max_length:
                chunks.append('\n'.join(current_chunk))
                current_chunk = [line]
                current_length = line_length
            else:
                current_chunk.append(line)
                current_length += line_length
        
        if current_chunk:
            chunks.append('\n'.join(current_chunk))
        
        # Send each chunk
        responses = []
        for i, chunk in enumerate(chunks):
            prefix = "(continued...)\n" if i > 0 else ""
            response = self.send_message(
                channel_id,
                prefix + chunk,
                thread_ts=thread_ts
            )
            responses.append(response)
        
        return responses

# Create a singleton instance
slack_service = SlackService(app)
