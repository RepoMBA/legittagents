import logging

from dotenv import load_dotenv
_ = load_dotenv(override=True)

logger = logging.getLogger("dlai-agent")
logger.setLevel(logging.INFO)

from livekit import agents
from livekit.agents import Agent, AgentSession, JobContext, WorkerOptions, jupyter
from livekit.plugins import (
    openai,
    elevenlabs,
    silero,
)
from livekit.agents import cli  # Add this import
from livekit.agents.metrics import LLMMetrics, STTMetrics, TTSMetrics, EOUMetrics
import asyncio
class Assistant(Agent):
    def __init__(self) -> None:
        llm = openai.LLM(model="gpt-o4-mini")
        stt = openai.STT()
        tts = openai.TTS()
        #tts = elevenlabs.TTS(voice_id="CwhRBWXzGAHq8TQ4Fs17")  # example with defined voice
        silero_vad = silero.VAD.load()

        super().__init__(
            instructions="""
                You are an AI interviewer conducting a professional job interview via voice. 
                Your role is to:
                
                1. Welcome the candidate warmly and explain the interview process
                2. Ask relevant questions about their experience, skills, and background
                3. Follow up on their responses with probing questions when appropriate
                4. Assess technical competencies related to the role
                5. Evaluate cultural fit and soft skills
                6. Give the candidate opportunities to ask questions about the role/company
                7. Maintain a professional yet friendly tone throughout
                8. Take notes mentally on key responses for evaluation
                
                Interview Structure:
                - Start with introductions and overview
                - Ask about their background and experience
                - Dive into technical/role-specific questions
                - Explore behavioral scenarios
                - Allow time for candidate questions
                - Conclude professionally
                
                Keep responses conversational and natural. Ask one question at a time.
                Listen actively and build on their responses. Be encouraging while staying objective.
            """,
            stt=stt,
            llm=llm,
            tts=tts,
            vad=silero_vad,
        )

class InterviewAgent(Agent):
    def __init__(self) -> None:
        llm = openai.LLM(model="gpt-4o-mini")
        #llm = openai.LLM(model="gpt-4o-mini")   # Example with lower latency
        stt = openai.STT(model="whisper-1")
        tts = openai.TTS()
        #tts = elevenlabs.TTS()
        silero_vad = silero.VAD.load()
        
        super().__init__(
            instructions="""
                You are an experienced AI interviewer conducting professional job interviews via voice.
                
                Your responsibilities:
                1. Create a welcoming, professional atmosphere
                2. Conduct structured yet conversational interviews
                3. Ask relevant questions based on the role requirements
                4. Evaluate both technical skills and cultural fit
                5. Provide clear next steps at the end
                
                Interview Flow:
                - Welcome & Introduction (1-2 minutes)
                - Background & Experience Discussion (5-10 minutes)  
                - Technical/Role-Specific Questions (10-15 minutes)
                - Behavioral & Situational Questions (5-10 minutes)
                - Candidate Questions & Wrap-up (5 minutes)
                
                Guidelines:
                - Ask one clear question at a time
                - Listen actively and ask follow-up questions
                - Keep track of time and coverage
                - Be encouraging but objective
                - Take mental notes on key responses
                - Adapt questions based on the candidate's background
                
                Start by introducing yourself and asking the candidate to briefly introduce themselves.
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
        print("\n--- LLM Metrics ---")
        print(f"Prompt Tokens: {metrics.prompt_tokens}")
        print(f"Completion Tokens: {metrics.completion_tokens}")
        print(f"Tokens per second: {metrics.tokens_per_second:.4f}")
        print(f"TTFT: {metrics.ttft:.4f}s")
        print("------------------\n")

    async def on_stt_metrics_collected(self, metrics: STTMetrics) -> None:
        print("\n--- STT Metrics ---")
        print(f"Duration: {metrics.duration:.4f}s")
        print(f"Audio Duration: {metrics.audio_duration:.4f}s")
        print(f"Streamed: {'Yes' if metrics.streamed else 'No'}")
        print("------------------\n")

    async def on_eou_metrics_collected(self, metrics: EOUMetrics) -> None:
        print("\n--- End of Utterance Metrics ---")
        print(f"End of Utterance Delay: {metrics.end_of_utterance_delay:.4f}s")
        print(f"Transcription Delay: {metrics.transcription_delay:.4f}s")
        print("--------------------------------\n")

    async def on_tts_metrics_collected(self, metrics: TTSMetrics) -> None:
        print("\n--- TTS Metrics ---")
        print(f"TTFB: {metrics.ttfb:.4f}s")
        print(f"Duration: {metrics.duration:.4f}s")
        print(f"Audio Duration: {metrics.audio_duration:.4f}s")
        print(f"Streamed: {'Yes' if metrics.streamed else 'No'}")
        print("------------------\n")


async def entrypoint(ctx: JobContext):
    await ctx.connect()

    session = AgentSession()

    await session.start(
        agent=InterviewAgent(),
        room=ctx.room,
    )

if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))