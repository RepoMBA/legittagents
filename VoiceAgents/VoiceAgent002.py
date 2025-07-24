import logging
import os
import time

from dotenv import load_dotenv
_ = load_dotenv(override=True)

logger = logging.getLogger("voice-candidate-agent")
logger.setLevel(logging.INFO)

logger.info(f"OPENAI_API_KEY is {'SET' if os.getenv('OPENAI_API_KEY') else 'NOT SET'}")
logger.info(f"LIVEKIT_API_KEY is {'SET' if os.getenv('LIVEKIT_API_KEY') else 'NOT SET'}")
logger.info(f"LIVEKIT_URL = {os.getenv('LIVEKIT_URL', 'NOT SET')}")

from livekit.agents import Agent, AgentSession, JobContext, WorkerOptions
from livekit.plugins import (
    openai,
    elevenlabs,
    silero,
)
from livekit.agents import cli
from livekit.agents.metrics import LLMMetrics, STTMetrics, TTSMetrics, EOUMetrics
import asyncio

# Import audio router if available
try:
    from audio_router import AudioRouter
    AUDIO_ROUTER_AVAILABLE = True
    logger.info("Audio router integration available")
except ImportError:
    logger.warning("Audio router not available - metrics tracking disabled")
    AUDIO_ROUTER_AVAILABLE = False

class VoiceCandidateAgent(Agent):
    def __init__(self) -> None:
        llm = openai.LLM(model="gpt-4o-mini")
        stt = openai.STT(model="gpt-4o-transcribe")
        tts = openai.TTS(model="gpt-4o-mini-tts")
        silero_vad = silero.VAD.load()
        
        # Initialize audio router for metrics tracking
        self.audio_router = AudioRouter() if AUDIO_ROUTER_AVAILABLE else None
        self.response_start_time = None
        
        super().__init__(
            instructions="""
                You are a professional job candidate being interviewed for a position. 
                Your role is to:
                
                1. Respond professionally and thoughtfully to interview questions
                2. Provide specific examples from your experience when asked
                3. Ask clarifying questions when appropriate
                4. Show enthusiasm for the role and company
                5. Be honest about your qualifications and experience
                6. Demonstrate good communication skills
                
                Your Background:
                - You are Alex Johnson, a software engineer with 5 years of experience
                - Bachelor's degree in Computer Science from UC Berkeley
                - Experience with Python, JavaScript, React, Node.js, PostgreSQL
                - Previously worked at TechFlow as a Senior Developer
                - Led a team of 4 developers building microservices
                - Current notice period: 2 weeks
                - Available to start: February 15th, 2025  
                - Based in: San Francisco, California
                - AWS and Docker experience
                
                Interview Guidelines:
                - Answer questions directly and concisely
                - Provide concrete examples when discussing experience
                - Ask thoughtful questions about the role and company
                - Show genuine interest in the opportunity
                - Be personable while maintaining professionalism
                - If you don't know something, be honest about it
                
                Remember: You are the candidate, not the interviewer. Wait for questions and respond appropriately.
            """,
            stt=stt,
            llm=llm,
            tts=tts,
            vad=silero_vad,
        )

        def llm_metrics_wrapper(metrics: LLMMetrics):
            asyncio.create_task(self.on_llm_metrics_collected(metrics))
        llm.on("metrics_collected", llm_metrics_wrapper)

        def stt_metrics_wrapper(metrics: STTMetrics):
            asyncio.create_task(self.on_stt_metrics_collected(metrics))
        stt.on("metrics_collected", stt_metrics_wrapper)

        def eou_metrics_wrapper(metrics: EOUMetrics):
            asyncio.create_task(self.on_eou_metrics_collected(metrics))
        stt.on("eou_metrics_collected", eou_metrics_wrapper)

        def tts_metrics_wrapper(metrics: TTSMetrics):
            asyncio.create_task(self.on_tts_metrics_collected(metrics))
        tts.on("metrics_collected", tts_metrics_wrapper)

    async def on_llm_metrics_collected(self, metrics: LLMMetrics) -> None:
        print("\n--- Candidate LLM Metrics ---")
        print(f"Prompt Tokens: {metrics.prompt_tokens}")
        print(f"Completion Tokens: {metrics.completion_tokens}")
        print(f"Tokens per second: {metrics.tokens_per_second:.4f}")
        print(f"TTFT: {metrics.ttft:.4f}s")
        print("----------------------------\n")
        
        # Track response timing
        if self.response_start_time and self.audio_router:
            response_end = time.time()
            self.audio_router.track_response(
                "candidate", 
                self.response_start_time, 
                response_end
            )

    async def on_stt_metrics_collected(self, metrics: STTMetrics) -> None:
        print("\n--- Candidate STT Metrics ---")
        print(f"Duration: {metrics.duration:.4f}s")
        print(f"Audio Duration: {metrics.audio_duration:.4f}s")
        print(f"Streamed: {'Yes' if metrics.streamed else 'No'}")
        print("----------------------------\n")
        
        # Mark response start time
        self.response_start_time = time.time()

    async def on_eou_metrics_collected(self, metrics: EOUMetrics) -> None:
        print("\n--- Candidate End of Utterance Metrics ---")
        print(f"End of Utterance Delay: {metrics.end_of_utterance_delay:.4f}s")
        print(f"Transcription Delay: {metrics.transcription_delay:.4f}s")
        print("------------------------------------------\n")

    async def on_tts_metrics_collected(self, metrics: TTSMetrics) -> None:
        print("\n--- Candidate TTS Metrics ---")
        print(f"TTFB: {metrics.ttfb:.4f}s")
        print(f"Duration: {metrics.duration:.4f}s")
        print(f"Audio Duration: {metrics.audio_duration:.4f}s")
        print(f"Streamed: {'Yes' if metrics.streamed else 'No'}")
        print("----------------------------\n")


async def entrypoint(ctx: JobContext):
    await ctx.connect()

    session = AgentSession()

    await session.start(
        agent=VoiceCandidateAgent(),
        room=ctx.room,
    )

if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
    

