"""
Audio Router for Voice Agent Testing

This module handles audio routing between interviewer and candidate agents,
including virtual audio cable setup and recording functionality.
"""

import asyncio
import logging
import os
import time
import json
from datetime import datetime
from typing import Dict, List, Optional
import sounddevice as sd
import soundfile as sf
import numpy as np
from dataclasses import dataclass, asdict
from pathlib import Path

# Set up logging
logger = logging.getLogger("audio-router")
logger.setLevel(logging.INFO)

@dataclass
class AudioMetrics:
    """Track audio and conversation metrics"""
    timestamp: float
    agent_type: str  # "interviewer" or "candidate"
    response_latency: float
    audio_duration: float
    voice_activity_ratio: float  # % of time with voice activity
    audio_quality_score: float  # 0-1 scale
    interruption_detected: bool
    technical_issues: List[str]
    
    def to_dict(self):
        return asdict(self)

@dataclass
class ConversationMetrics:
    """Track overall conversation quality"""
    conversation_id: str
    start_time: float
    end_time: float
    total_duration: float
    interviewer_talk_time: float
    candidate_talk_time: float
    turn_count: int
    interruption_count: int
    technical_issue_count: int
    average_response_latency: float
    conversation_flow_score: float  # 0-1 scale
    audio_metrics: List[AudioMetrics]
    
    def to_dict(self):
        return {
            **asdict(self),
            'audio_metrics': [metric.to_dict() for metric in self.audio_metrics]
        }

class AudioRouter:
    """Handles audio routing and recording for voice agent testing"""
    
    def __init__(self, sample_rate: int = 44100, channels: int = 1):
        self.sample_rate = sample_rate
        self.channels = channels
        self.recording = False
        self.recordings = {
            'interviewer': [],
            'candidate': [],
            'mixed': []
        }
        self.metrics = []
        self.conversation_metrics = None
        self.last_speech_time = {}
        
        # Create recordings directory
        self.recordings_dir = Path("recordings")
        self.recordings_dir.mkdir(exist_ok=True)
        
        # Audio analysis parameters
        self.silence_threshold = 0.01
        self.min_speech_duration = 0.5
        
        logger.info("AudioRouter initialized")
        self._detect_audio_devices()
    
    def _detect_audio_devices(self):
        """Detect available audio devices for virtual cable setup"""
        logger.info("Detecting audio devices...")
        devices = sd.query_devices()
        
        virtual_cables = []
        blackhole_detected = False
        
        for i, device in enumerate(devices):
            device_name = device['name'].lower()
            if 'blackhole' in device_name:
                virtual_cables.append((i, device['name']))
                blackhole_detected = True
                is_input = device['max_input_channels'] > 0
                is_output = device['max_output_channels'] > 0
                logger.info(f"✅ Found BlackHole device: {device['name']} (ID: {i})")
                logger.info(f"   Channels: In={device['max_input_channels']}, Out={device['max_output_channels']}")
                logger.info(f"   Sample Rate: {device['default_samplerate']}Hz")  
                logger.info(f"   Capabilities: {'Input ' if is_input else ''}{'Output' if is_output else ''}")
            elif any(cable in device_name for cable in ['vb-audio', 'soundflower', 'virtual', 'cable']):
                virtual_cables.append((i, device['name']))
                logger.info(f"Found virtual audio cable: {device['name']} (ID: {i})")
        
        if blackhole_detected:
            logger.info("🎧 BlackHole detected! Audio routing should work properly now.")
            # Check if BlackHole is set as default
            try:
                default_input = sd.query_devices(kind='input')
                default_output = sd.query_devices(kind='output')
                
                logger.info(f"Current Default Input: {default_input['name']}")
                logger.info(f"Current Default Output: {default_output['name']}")
                
                if 'blackhole' in default_input['name'].lower() and 'blackhole' in default_output['name'].lower():
                    logger.info("✅ Both input and output are set to BlackHole - Perfect!")
                else:
                    logger.warning("⚠️  For best results, set both input and output to BlackHole in System Settings")
            except Exception as e:
                logger.warning(f"Could not check default audio devices: {e}")
                
        elif not virtual_cables:
            logger.warning("No virtual audio cables detected. Install BlackHole for macOS or VB-Audio Cable for Windows")
            logger.info("Available devices:")
            for i, device in enumerate(devices):
                logger.info(f"  {i}: {device['name']}")
            logger.info("📖 Install BlackHole from: https://github.com/ExistentialAudio/BlackHole")
        
        return virtual_cables
    
    def setup_virtual_audio_routing(self):
        """Setup instructions for virtual audio cable routing"""
        instructions = """
        🎧 VIRTUAL AUDIO CABLE SETUP
        ================================
        
        For macOS (BlackHole - RECOMMENDED):
        1. Install BlackHole from https://github.com/ExistentialAudio/BlackHole
        2. Go to System Settings → Sound
        3. Set both Input and Output to "BlackHole 2ch"
        4. For monitoring: Create Multi-Output Device in Audio MIDI Setup
           - Include BlackHole 2ch + your speakers/headphones
           - Set as system output for audio monitoring
        
        For Windows (VB-Audio Cable):
        1. Download and install VB-Audio Cable from https://vb-audio.com/Cable/
        2. Set VB-Cable as default playback device for candidate agent
        3. Set VB-Cable as default recording device for interviewer agent
        4. Use physical audio device for your monitoring
        
        Alternative for macOS (SoundFlower - Legacy):
        1. Install SoundFlower from https://github.com/mattingalls/Soundflower
        2. Create Multi-Output Device in Audio MIDI Setup:
           - Add SoundFlower (2ch) and your speakers
        3. Set Multi-Output Device as system output
        4. Set SoundFlower (2ch) as input for interviewer agent
        
        Testing Setup:
        - Candidate Agent Output → Virtual Cable Input
        - Interviewer Agent Input ← Virtual Cable Output
        - Monitor both on physical speakers/headphones
        """
        
        print(instructions)
        logger.info("Virtual audio routing instructions provided")
        return instructions
        return instructions
    
    def start_recording(self, conversation_id: str):
        """Start recording audio from both agents"""
        self.conversation_id = conversation_id
        self.recording = True
        self.start_time = time.time()
        
        # Initialize conversation metrics
        self.conversation_metrics = ConversationMetrics(
            conversation_id=conversation_id,
            start_time=self.start_time,
            end_time=0,
            total_duration=0,
            interviewer_talk_time=0,
            candidate_talk_time=0,
            turn_count=0,
            interruption_count=0,
            technical_issue_count=0,
            average_response_latency=0,
            conversation_flow_score=0,
            audio_metrics=[]
        )
        
        logger.info(f"Started recording conversation: {conversation_id}")
        
        # Start audio capture in background
        asyncio.create_task(self._record_audio())
    
    async def _record_audio(self):
        """Background task to record audio streams"""
        while self.recording:
            try:
                # This would typically capture from virtual audio devices
                # For now, we'll simulate the recording process
                await asyncio.sleep(0.1)
                
                # In a real implementation, you would:
                # 1. Capture audio from virtual cable
                # 2. Separate interviewer and candidate streams
                # 3. Analyze voice activity
                # 4. Detect interruptions and technical issues
                
            except Exception as e:
                logger.error(f"Error in audio recording: {e}")
                await asyncio.sleep(1)
    
    def stop_recording(self):
        """Stop recording and save files"""
        if not self.recording:
            return
        
        self.recording = False
        self.end_time = time.time()
        
        if self.conversation_metrics:
            self.conversation_metrics.end_time = self.end_time
            self.conversation_metrics.total_duration = self.end_time - self.start_time
            
            # Calculate final metrics
            if self.metrics:
                self.conversation_metrics.average_response_latency = sum(
                    m.response_latency for m in self.metrics
                ) / len(self.metrics)
                
                self.conversation_metrics.audio_metrics = self.metrics
        
        # Save recordings and metrics
        self._save_recordings()
        self._save_metrics()
        
        logger.info(f"Stopped recording. Duration: {self.conversation_metrics.total_duration:.2f}s")
    
    def track_response(self, agent_type: str, response_start: float, response_end: float, 
                      audio_data: Optional[np.ndarray] = None):
        """Track a single response for metrics"""
        try:
            current_time = time.time()
            response_latency = response_start - self.last_speech_time.get('other_agent', current_time)
            audio_duration = response_end - response_start
            
            # Analyze audio quality if data provided
            voice_activity_ratio = 0.8  # Placeholder
            audio_quality_score = 0.9   # Placeholder
            interruption_detected = False  # Placeholder
            technical_issues = []  # Placeholder
            
            if audio_data is not None:
                # Real audio analysis would go here
                voice_activity_ratio = self._calculate_voice_activity(audio_data)
                audio_quality_score = self._calculate_audio_quality(audio_data)
                interruption_detected = self._detect_interruption(audio_data)
                technical_issues = self._detect_technical_issues(audio_data)
            
            # Create metrics entry
            metrics = AudioMetrics(
                timestamp=current_time,
                agent_type=agent_type,
                response_latency=max(0, response_latency),
                audio_duration=audio_duration,
                voice_activity_ratio=voice_activity_ratio,
                audio_quality_score=audio_quality_score,
                interruption_detected=interruption_detected,
                technical_issues=technical_issues
            )
            
            self.metrics.append(metrics)
            self.last_speech_time[agent_type] = response_end
            
            # Update conversation metrics
            if self.conversation_metrics:
                if agent_type == "interviewer":
                    self.conversation_metrics.interviewer_talk_time += audio_duration
                else:
                    self.conversation_metrics.candidate_talk_time += audio_duration
                
                if interruption_detected:
                    self.conversation_metrics.interruption_count += 1
                
                if technical_issues:
                    self.conversation_metrics.technical_issue_count += len(technical_issues)
            
            logger.debug(f"Tracked {agent_type} response: {audio_duration:.2f}s, latency: {response_latency:.2f}s")
            
        except Exception as e:
            logger.error(f"Error tracking response: {e}")
    
    def _calculate_voice_activity(self, audio_data: np.ndarray) -> float:
        """Calculate percentage of time with voice activity"""
        try:
            # Simple energy-based voice activity detection
            energy = np.square(audio_data)
            voice_frames = np.sum(energy > self.silence_threshold)
            return voice_frames / len(audio_data) if len(audio_data) > 0 else 0
        except:
            return 0.0
    
    def _calculate_audio_quality(self, audio_data: np.ndarray) -> float:
        """Calculate audio quality score (0-1)"""
        try:
            # Simple SNR-based quality estimation
            signal_power = np.mean(np.square(audio_data))
            noise_floor = np.percentile(np.square(audio_data), 10)
            
            if noise_floor > 0:
                snr = 10 * np.log10(signal_power / noise_floor)
                return min(1.0, max(0.0, (snr - 10) / 30))  # Normalize 10-40 dB to 0-1
            return 0.8  # Default good quality
        except:
            return 0.5
    
    def _detect_interruption(self, audio_data: np.ndarray) -> bool:
        """Detect if this audio contains interruptions"""
        # Placeholder - would analyze for overlapping speech
        return False
    
    def _detect_technical_issues(self, audio_data: np.ndarray) -> List[str]:
        """Detect technical issues in audio"""
        issues = []
        
        try:
            # Check for dropouts (sudden silence)
            if len(audio_data) > 0:
                energy = np.square(audio_data)
                if np.max(energy) < 0.001:
                    issues.append("low_audio_level")
                
                # Check for clipping
                if np.max(np.abs(audio_data)) > 0.95:
                    issues.append("audio_clipping")
                
                # Check for dropouts (sudden silence in middle)
                silent_blocks = []
                block_size = self.sample_rate // 10  # 100ms blocks
                for i in range(0, len(audio_data) - block_size, block_size):
                    block_energy = np.mean(np.square(audio_data[i:i+block_size]))
                    if block_energy < 0.0001:
                        silent_blocks.append(i)
                
                if len(silent_blocks) > 2:  # Multiple silent blocks indicate dropouts
                    issues.append("audio_dropouts")
        
        except Exception as e:
            logger.error(f"Error detecting technical issues: {e}")
            issues.append("analysis_error")
        
        return issues
    
    def _save_recordings(self):
        """Save recorded audio files"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            for agent_type, audio_data in self.recordings.items():
                if audio_data:
                    filename = self.recordings_dir / f"{self.conversation_id}_{agent_type}_{timestamp}.wav"
                    # Convert list of arrays to single array
                    combined_audio = np.concatenate(audio_data) if audio_data else np.array([])
                    
                    if len(combined_audio) > 0:
                        sf.write(filename, combined_audio, self.sample_rate)
                        logger.info(f"Saved {agent_type} recording: {filename}")
        
        except Exception as e:
            logger.error(f"Error saving recordings: {e}")
    
    def _save_metrics(self):
        """Save conversation metrics to JSON"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = self.recordings_dir / f"{self.conversation_id}_metrics_{timestamp}.json"
            
            if self.conversation_metrics:
                with open(filename, 'w') as f:
                    json.dump(self.conversation_metrics.to_dict(), f, indent=2)
                
                logger.info(f"Saved conversation metrics: {filename}")
                
                # Print summary
                self._print_metrics_summary()
        
        except Exception as e:
            logger.error(f"Error saving metrics: {e}")
    
    def _print_metrics_summary(self):
        """Print a summary of the conversation metrics"""
        if not self.conversation_metrics:
            return
        
        cm = self.conversation_metrics
        
        print("\n" + "="*60)
        print("🎯 CONVERSATION ANALYSIS SUMMARY")
        print("="*60)
        print(f"Conversation ID: {cm.conversation_id}")
        print(f"Total Duration: {cm.total_duration:.2f}s")
        print(f"Interviewer Talk Time: {cm.interviewer_talk_time:.2f}s ({cm.interviewer_talk_time/cm.total_duration*100:.1f}%)")
        print(f"Candidate Talk Time: {cm.candidate_talk_time:.2f}s ({cm.candidate_talk_time/cm.total_duration*100:.1f}%)")
        print(f"Turn Count: {cm.turn_count}")
        print(f"Average Response Latency: {cm.average_response_latency:.2f}s")
        print(f"Interruptions: {cm.interruption_count}")
        print(f"Technical Issues: {cm.technical_issue_count}")
        
        if self.metrics:
            avg_quality = sum(m.audio_quality_score for m in self.metrics) / len(self.metrics)
            avg_voice_activity = sum(m.voice_activity_ratio for m in self.metrics) / len(self.metrics)
            
            print(f"Average Audio Quality: {avg_quality:.2f}/1.0")
            print(f"Average Voice Activity: {avg_voice_activity:.2f}")
            
            # Technical issues breakdown
            all_issues = []
            for m in self.metrics:
                all_issues.extend(m.technical_issues)
            
            if all_issues:
                issue_counts = {}
                for issue in all_issues:
                    issue_counts[issue] = issue_counts.get(issue, 0) + 1
                
                print("\nTechnical Issues Breakdown:")
                for issue, count in issue_counts.items():
                    print(f"  - {issue}: {count}")
        
        print("="*60)

# Example usage and testing
async def test_audio_routing():
    """Test the audio routing functionality"""
    print("🧪 Testing Audio Router")
    
    router = AudioRouter()
    
    # Show setup instructions
    router.setup_virtual_audio_routing()
    
    # Start recording
    conversation_id = f"test_interview_{int(time.time())}"
    router.start_recording(conversation_id)
    
    # Simulate some conversation
    print("\n🎭 Simulating interview conversation...")
    
    # Simulate interviewer speaking
    await asyncio.sleep(1)
    router.track_response("interviewer", time.time(), time.time() + 2.5)
    
    # Simulate candidate response
    await asyncio.sleep(0.5)  # Response latency
    router.track_response("candidate", time.time(), time.time() + 3.0)
    
    # Simulate more turns
    await asyncio.sleep(0.3)
    router.track_response("interviewer", time.time(), time.time() + 1.8)
    
    await asyncio.sleep(0.7)
    router.track_response("candidate", time.time(), time.time() + 4.2)
    
    # Stop recording after 10 seconds
    await asyncio.sleep(5)
    router.stop_recording()
    
    print("✅ Audio routing test completed")

if __name__ == "__main__":
    asyncio.run(test_audio_routing())
