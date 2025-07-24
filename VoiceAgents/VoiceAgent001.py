import logging

from dotenv import load_dotenv
_ = load_dotenv(override=True)

logger = logging.getLogger("dlai-agent")
logger.setLevel(logging.INFO)


from livekit.agents import Agent, AgentSession, JobContext, WorkerOptions
from livekit.plugins import (
    openai,
    elevenlabs,
    silero,
)
from livekit.agents import cli  # Add this import
from livekit.agents.metrics import LLMMetrics, STTMetrics, TTSMetrics, EOUMetrics
import asyncio

class InterviewAgent(Agent):
    def __init__(self) -> None:
        llm = openai.LLM(model="gpt-4o-mini")
        #llm = openai.LLM(model="gpt-4o-mini")   # Example with lower latency
        stt = openai.STT(model="gpt-4o-transcribe")
        tts = openai.TTS(model="gpt-4o-mini-tts", voice="ash")
        #tts = elevenlabs.TTS()
        silero_vad = silero.VAD.load()
        
        super().__init__(
            instructions="""
                You are an experienced AI interviewer conducting professional job interviews via voice.
                
                Your responsibilities:
                1. Create a welcoming, professional atmosphere
                2. Conduct structured yet conversational interviews (max 15 minutes)
                3. Ask relevant questions based on the role requirements
                4. Evaluate both technical skills and cultural fit
                5. Ensure all mandatory questions are covered before ending
                6. Provide clear next steps at the end
                
                MANDATORY QUESTIONS (must ask during interview unless candidate volunteers to quit):
                - What is your current notice period?
                - When can you start?
                - What city are you currently based out of?
                - What are your qualifications?
                
                Interview Flow (15 minutes total):
                - Welcome & Introduction (1-2 minutes)
                - Background, Experience & Qualifications (4-6 minutes)  
                - Technical/Role-Specific Questions (5-7 minutes)
                - Logistics: Notice period, start date, location (2-3 minutes)
                - Candidate Questions & Wrap-up (2-3 minutes)
                
                Guidelines:
                - Ask one clear question at a time
                - Listen actively and ask follow-up questions
                - Keep track of time and mandatory question coverage
                - Weave mandatory questions naturally into conversation flow
                - Be encouraging but objective
                - Take mental notes on key responses
                - DO NOT end the interview until all mandatory questions are answered OR the candidate requests to quit
                - Keep the pace moving to fit within 15 minutes
                
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