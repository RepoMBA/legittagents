#!/usr/bin/env python3
"""
LiveKit Conversation Transcript Extractor
Connects to the LiveKit room and extracts real-time conversation data
"""

import asyncio
import json
import os
from datetime import datetime
from typing import Dict, List, Any
from livekit import api, rtc
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ConversationTranscriptExtractor:
    def __init__(self, room_name: str = "interview-room"):
        self.room_name = room_name
        self.conversation_data = {
            "metadata": {
                "session_id": f"transcript_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                "room_name": room_name,
                "start_time": datetime.now().isoformat(),
                "end_time": None,
                "total_duration": 0
            },
            "participants": {},
            "conversation_flow": [],
            "audio_events": [],
            "statistics": {
                "total_messages": 0,
                "participant_talk_time": {},
                "message_types": {}
            }
        }
        self.room = None
        self.start_time = datetime.now()
        
    async def connect_to_room(self):
        """Connect to the LiveKit room as an observer"""
        try:
            # Generate access token for observer
            token = api.AccessToken() \
                .with_identity("transcript-extractor") \
                .with_name("Transcript Extractor") \
                .with_grants(api.VideoGrants(
                    room_join=True,
                    room=self.room_name,
                    can_subscribe=True,
                    can_publish=False
                ))
            
            # Use development credentials
            jwt_token = token.to_jwt(
                api_key=os.getenv("LIVEKIT_API_KEY", "devkey"),
                api_secret=os.getenv("LIVEKIT_API_SECRET", "secret")
            )
            
            # Connect to room
            self.room = rtc.Room()
            self.setup_event_handlers()
            
            logger.info(f"Connecting to room: {self.room_name}")
            await self.room.connect(
                url=os.getenv("LIVEKIT_URL", "ws://localhost:7880"),
                token=jwt_token
            )
            
            logger.info("Successfully connected to LiveKit room")
            return True
            
        except Exception as e:
            logger.error(f"Failed to connect to room: {e}")
            return False
    
    def setup_event_handlers(self):
        """Setup event handlers for room events"""
        self.room.on("participant_connected", self.on_participant_connected)
        self.room.on("participant_disconnected", self.on_participant_disconnected)
        self.room.on("track_subscribed", self.on_track_subscribed)
        self.room.on("track_unsubscribed", self.on_track_unsubscribed)
        self.room.on("data_received", self.on_data_received)
        
    def on_participant_connected(self, participant: rtc.RemoteParticipant):
        """Handle participant connection"""
        participant_info = {
            "identity": participant.identity,
            "name": participant.name,
            "join_time": datetime.now().isoformat(),
            "metadata": participant.metadata
        }
        
        self.conversation_data["participants"][participant.identity] = participant_info
        
        event = {
            "timestamp": datetime.now().isoformat(),
            "type": "participant_joined",
            "participant": participant.identity,
            "data": participant_info
        }
        self.conversation_data["audio_events"].append(event)
        
        logger.info(f"Participant connected: {participant.identity}")
        
    def on_participant_disconnected(self, participant: rtc.RemoteParticipant):
        """Handle participant disconnection"""
        if participant.identity in self.conversation_data["participants"]:
            self.conversation_data["participants"][participant.identity]["leave_time"] = datetime.now().isoformat()
        
        event = {
            "timestamp": datetime.now().isoformat(),
            "type": "participant_left",
            "participant": participant.identity,
            "data": {}
        }
        self.conversation_data["audio_events"].append(event)
        
        logger.info(f"Participant disconnected: {participant.identity}")
        
    def on_track_subscribed(self, track: rtc.Track, publication: rtc.TrackPublication, participant: rtc.RemoteParticipant):
        """Handle track subscription"""
        event = {
            "timestamp": datetime.now().isoformat(),
            "type": "track_subscribed",
            "participant": participant.identity,
            "data": {
                "track_sid": track.sid,
                "track_kind": track.kind.name,
                "track_source": publication.source.name
            }
        }
        self.conversation_data["audio_events"].append(event)
        
        logger.info(f"Subscribed to {track.kind.name} track from {participant.identity}")
        
        # If it's an audio track, we can potentially extract speech-to-text here
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            logger.info(f"Audio track detected from {participant.identity}")
            
    def on_track_unsubscribed(self, track: rtc.Track, publication: rtc.TrackPublication, participant: rtc.RemoteParticipant):
        """Handle track unsubscription"""
        event = {
            "timestamp": datetime.now().isoformat(),
            "type": "track_unsubscribed",
            "participant": participant.identity,
            "data": {
                "track_sid": track.sid,
                "track_kind": track.kind.name
            }
        }
        self.conversation_data["audio_events"].append(event)
        
        logger.info(f"Unsubscribed from {track.kind.name} track from {participant.identity}")
        
    def on_data_received(self, data: bytes, participant: rtc.RemoteParticipant):
        """Handle data messages (could contain transcripts)"""
        try:
            # Try to decode as JSON (might contain transcript data)
            message_data = json.loads(data.decode('utf-8'))
            
            if isinstance(message_data, dict) and 'transcript' in message_data:
                # This is a transcript message
                conversation_entry = {
                    "timestamp": datetime.now().isoformat(),
                    "participant": participant.identity,
                    "message": message_data.get('transcript', ''),
                    "confidence": message_data.get('confidence', 0.0),
                    "type": message_data.get('type', 'speech'),
                    "duration": message_data.get('duration', 0.0)
                }
                
                self.conversation_data["conversation_flow"].append(conversation_entry)
                self.conversation_data["statistics"]["total_messages"] += 1
                
                # Update talk time statistics
                if participant.identity not in self.conversation_data["statistics"]["participant_talk_time"]:
                    self.conversation_data["statistics"]["participant_talk_time"][participant.identity] = 0.0
                
                self.conversation_data["statistics"]["participant_talk_time"][participant.identity] += conversation_entry["duration"]
                
                logger.info(f"Transcript from {participant.identity}: {message_data.get('transcript', '')}")
                
        except (json.JSONDecodeError, UnicodeDecodeError):
            # Not a JSON message, might be binary data
            event = {
                "timestamp": datetime.now().isoformat(),
                "type": "data_received",
                "participant": participant.identity,
                "data": {
                    "size": len(data),
                    "type": "binary"
                }
            }
            self.conversation_data["audio_events"].append(event)
            
    def save_transcript(self, filename: str = None):
        """Save the conversation transcript to a JSON file"""
        if filename is None:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"conversation_transcript_{timestamp}.json"
            
        # Update metadata
        self.conversation_data["metadata"]["end_time"] = datetime.now().isoformat()
        self.conversation_data["metadata"]["total_duration"] = (datetime.now() - self.start_time).total_seconds()
        
        # Calculate final statistics
        self.conversation_data["statistics"]["total_participants"] = len(self.conversation_data["participants"])
        self.conversation_data["statistics"]["total_audio_events"] = len(self.conversation_data["audio_events"])
        
        # Save to file
        filepath = os.path.join(os.path.dirname(__file__), filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(self.conversation_data, f, indent=2, ensure_ascii=False)
            
        logger.info(f"Transcript saved to: {filepath}")
        return filepath
        
    async def run_extraction(self, duration_seconds: int = 120):
        """Run the transcript extraction for a specified duration"""
        if not await self.connect_to_room():
            logger.error("Failed to connect to room")
            return None
            
        logger.info(f"Starting transcript extraction for {duration_seconds} seconds...")
        
        try:
            # Wait for the specified duration
            await asyncio.sleep(duration_seconds)
            
        except KeyboardInterrupt:
            logger.info("Extraction interrupted by user")
            
        finally:
            # Save transcript and disconnect
            filepath = self.save_transcript()
            if self.room:
                await self.room.disconnect()
            return filepath

async def main():
    """Main function to run transcript extraction"""
    extractor = ConversationTranscriptExtractor()
    
    print("🎙️  LiveKit Conversation Transcript Extractor")
    print("=" * 50)
    print(f"Room: {extractor.room_name}")
    print("Press Ctrl+C to stop extraction and save transcript")
    print()
    
    try:
        filepath = await extractor.run_extraction(duration_seconds=300)  # 5 minutes
        if filepath:
            print(f"✅ Transcript saved to: {filepath}")
        else:
            print("❌ Failed to extract transcript")
            
    except KeyboardInterrupt:
        print("\n🛑 Extraction stopped by user")
        filepath = extractor.save_transcript()
        print(f"✅ Transcript saved to: {filepath}")

if __name__ == "__main__":
    asyncio.run(main())
