#!/usr/bin/env python3
"""
Voice Agent Conversation Analyzer
Analyzes existing conversation data and creates structured JSON output
"""

import json
import os
import re
from datetime import datetime
from typing import Dict, List, Any, Optional

class ConversationAnalyzer:
    def __init__(self):
        self.conversation_data = {
            "metadata": {
                "analysis_timestamp": datetime.now().isoformat(),
                "source": "voice_agents_analysis",
                "version": "1.0"
            },
            "sessions": [],
            "summary": {
                "total_sessions": 0,
                "total_turns": 0,
                "participants": [],
                "topics_discussed": [],
                "key_insights": []
            }
        }
    
    def analyze_existing_transcript(self, filepath: str) -> Dict[str, Any]:
        """Analyze an existing transcript JSON file"""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                transcript_data = json.load(f)
            
            # Extract session information
            session_analysis = {
                "session_id": transcript_data.get("metadata", {}).get("timestamp", "unknown"),
                "duration": transcript_data.get("metadata", {}).get("duration_seconds", 0),
                "participants": [],
                "conversation_summary": self._extract_conversation_summary(transcript_data),
                "topics": self._extract_topics(transcript_data),
                "metrics": transcript_data.get("metrics", {}),
                "key_moments": self._identify_key_moments(transcript_data)
            }
            
            # Add to main conversation data
            self.conversation_data["sessions"].append(session_analysis)
            self._update_global_summary(session_analysis)
            
            return session_analysis
            
        except Exception as e:
            print(f"Error analyzing transcript {filepath}: {e}")
            return {}
    
    def _extract_conversation_summary(self, transcript_data: Dict) -> Dict[str, Any]:
        """Extract a summary of the conversation"""
        conversation_flow = transcript_data.get("conversation_flow", [])
        
        if not conversation_flow:
            return {"summary": "No conversation data available"}
        
        # Count turns by speaker
        speaker_turns = {}
        topics_mentioned = []
        
        for turn in conversation_flow:
            speaker = turn.get("speaker", "unknown")
            message = turn.get("message", "")
            
            if speaker not in speaker_turns:
                speaker_turns[speaker] = 0
            speaker_turns[speaker] += 1
            
            # Extract potential topics (simple keyword detection)
            topics_mentioned.extend(self._extract_keywords_from_message(message))
        
        return {
            "total_turns": len(conversation_flow),
            "speaker_distribution": speaker_turns,
            "duration": transcript_data.get("metadata", {}).get("duration_seconds", 0),
            "topics_mentioned": list(set(topics_mentioned)),
            "conversation_type": self._determine_conversation_type(conversation_flow)
        }
    
    def _extract_topics(self, transcript_data: Dict) -> List[str]:
        """Extract main topics from the conversation"""
        conversation_flow = transcript_data.get("conversation_flow", [])
        topics = set()
        
        # Keywords that indicate specific topics
        topic_keywords = {
            "technical_skills": ["python", "javascript", "react", "node.js", "aws", "docker", "microservices", "database"],
            "experience": ["years", "experience", "worked", "led", "team", "project", "company"],
            "education": ["degree", "university", "bachelor", "master", "graduated", "studied"],
            "availability": ["notice period", "start date", "available", "when can you start"],
            "location": ["based", "location", "city", "remote", "office"],
            "company_culture": ["team", "culture", "values", "environment", "work-life balance"],
            "challenges": ["challenging", "difficult", "problem", "solution", "overcome"],
            "future_goals": ["goals", "career", "future", "aspiration", "next step"]
        }
        
        for turn in conversation_flow:
            message = turn.get("message", "").lower()
            
            for topic, keywords in topic_keywords.items():
                if any(keyword in message for keyword in keywords):
                    topics.add(topic)
        
        return list(topics)
    
    def _extract_keywords_from_message(self, message: str) -> List[str]:
        """Extract important keywords from a message"""
        # Simple keyword extraction - can be enhanced with NLP
        important_keywords = [
            "python", "javascript", "react", "node.js", "aws", "docker", "kubernetes",
            "microservices", "database", "postgresql", "mongodb", "redis",
            "experience", "years", "team", "lead", "project", "company",
            "degree", "university", "bachelor", "master", "certification",
            "agile", "scrum", "ci/cd", "devops", "testing", "debugging"
        ]
        
        message_lower = message.lower()
        found_keywords = [kw for kw in important_keywords if kw in message_lower]
        return found_keywords
    
    def _determine_conversation_type(self, conversation_flow: List[Dict]) -> str:
        """Determine the type of conversation based on content"""
        if not conversation_flow:
            return "unknown"
        
        # Check for interview-specific patterns
        interview_indicators = ["interview", "notice period", "start date", "qualifications", "experience"]
        casual_indicators = ["how are you", "weather", "weekend", "hobby"]
        technical_indicators = ["code", "algorithm", "system design", "architecture", "debugging"]
        
        all_text = " ".join([turn.get("message", "").lower() for turn in conversation_flow])
        
        interview_score = sum(1 for indicator in interview_indicators if indicator in all_text)
        casual_score = sum(1 for indicator in casual_indicators if indicator in all_text)
        technical_score = sum(1 for indicator in technical_indicators if indicator in all_text)
        
        if interview_score >= 2:
            return "job_interview"
        elif technical_score >= 2:
            return "technical_discussion"
        elif casual_score >= 2:
            return "casual_conversation"
        else:
            return "general_discussion"
    
    def _identify_key_moments(self, transcript_data: Dict) -> List[Dict[str, Any]]:
        """Identify key moments in the conversation"""
        conversation_flow = transcript_data.get("conversation_flow", [])
        key_moments = []
        
        for turn in conversation_flow:
            message = turn.get("message", "")
            turn_type = turn.get("type", "")
            
            # Identify different types of key moments
            if turn_type == "opening":
                key_moments.append({
                    "type": "conversation_start",
                    "timestamp": turn.get("timestamp"),
                    "speaker": turn.get("speaker"),
                    "description": "Conversation initiated",
                    "content": message[:100] + "..." if len(message) > 100 else message
                })
            
            elif turn_type == "mandatory_question":
                key_moments.append({
                    "type": "important_question",
                    "timestamp": turn.get("timestamp"),
                    "speaker": turn.get("speaker"),
                    "description": "Key interview question asked",
                    "content": message
                })
            
            elif turn_type == "technical_question":
                key_moments.append({
                    "type": "technical_assessment",
                    "timestamp": turn.get("timestamp"),
                    "speaker": turn.get("speaker"),
                    "description": "Technical question posed",
                    "content": message
                })
            
            elif turn_type == "closing":
                key_moments.append({
                    "type": "conversation_end",
                    "timestamp": turn.get("timestamp"),
                    "speaker": turn.get("speaker"),
                    "description": "Conversation concluded",
                    "content": message
                })
            
            # Check for long responses (potentially detailed answers)
            elif len(message) > 200:
                key_moments.append({
                    "type": "detailed_response",
                    "timestamp": turn.get("timestamp"),
                    "speaker": turn.get("speaker"),
                    "description": "Comprehensive answer provided",
                    "content": message[:150] + "..."
                })
        
        return key_moments
    
    def _update_global_summary(self, session_analysis: Dict):
        """Update the global summary with session data"""
        self.conversation_data["summary"]["total_sessions"] += 1
        
        if "conversation_summary" in session_analysis:
            self.conversation_data["summary"]["total_turns"] += session_analysis["conversation_summary"].get("total_turns", 0)
        
        # Add topics to global list
        session_topics = session_analysis.get("topics", [])
        for topic in session_topics:
            if topic not in self.conversation_data["summary"]["topics_discussed"]:
                self.conversation_data["summary"]["topics_discussed"].append(topic)
    
    def generate_insights(self) -> List[str]:
        """Generate key insights from all analyzed conversations"""
        insights = []
        
        if self.conversation_data["summary"]["total_sessions"] > 0:
            avg_turns = self.conversation_data["summary"]["total_turns"] / self.conversation_data["summary"]["total_sessions"]
            insights.append(f"Average conversation length: {avg_turns:.1f} turns")
        
        if self.conversation_data["summary"]["topics_discussed"]:
            most_common_topics = self.conversation_data["summary"]["topics_discussed"][:3]
            insights.append(f"Most discussed topics: {', '.join(most_common_topics)}")
        
        # Add more sophisticated insights based on patterns
        for session in self.conversation_data["sessions"]:
            if session.get("conversation_summary", {}).get("conversation_type") == "job_interview":
                insights.append("Interview simulation detected - structured Q&A format observed")
                break
        
        return insights
    
    def save_analysis(self, filename: str = None) -> str:
        """Save the complete analysis to a JSON file"""
        if filename is None:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"conversation_analysis_{timestamp}.json"
        
        # Generate final insights
        self.conversation_data["summary"]["key_insights"] = self.generate_insights()
        
        filepath = os.path.join(os.path.dirname(__file__), filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(self.conversation_data, f, indent=2, ensure_ascii=False)
        
        return filepath

def main():
    """Main function to analyze existing conversations"""
    analyzer = ConversationAnalyzer()
    
    print("🤖 Voice Agent Conversation Analyzer")
    print("=" * 50)
    
    # Look for existing transcript files
    current_dir = os.path.dirname(__file__)
    transcript_files = [f for f in os.listdir(current_dir) if f.endswith('.json') and 'simulation' in f]
    
    if not transcript_files:
        print("❌ No transcript files found")
        return
    
    print(f"Found {len(transcript_files)} transcript file(s):")
    for i, filename in enumerate(transcript_files, 1):
        print(f"  {i}. {filename}")
    
    print("\nAnalyzing conversations...")
    
    # Analyze each transcript file
    for filename in transcript_files:
        filepath = os.path.join(current_dir, filename)
        print(f"📊 Analyzing: {filename}")
        session_analysis = analyzer.analyze_existing_transcript(filepath)
        
        if session_analysis:
            print(f"  ✅ Session analyzed - {session_analysis.get('conversation_summary', {}).get('total_turns', 0)} turns")
    
    # Save complete analysis
    analysis_file = analyzer.save_analysis()
    print(f"\n✅ Complete analysis saved to: {os.path.basename(analysis_file)}")
    
    # Print summary
    summary = analyzer.conversation_data["summary"]
    print(f"\n📈 Summary:")
    print(f"  Total sessions: {summary['total_sessions']}")
    print(f"  Total turns: {summary['total_turns']}")
    print(f"  Topics discussed: {', '.join(summary['topics_discussed'][:5])}")
    
    if summary['key_insights']:
        print(f"\n💡 Key Insights:")
        for insight in summary['key_insights']:
            print(f"  • {insight}")

if __name__ == "__main__":
    main()
