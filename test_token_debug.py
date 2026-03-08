"""num_predict가 실제로 Ollama에 전달되는지, 응답 메타데이터 확인"""
import sys
sys.stdout.reconfigure(encoding="utf-8")

from langchain_ollama import ChatOllama
from langchain_core.messages import SystemMessage, HumanMessage

# 1. ChatOllama가 num_predict를 어떻게 처리하는지 확인
llm = ChatOllama(
    model="qwen3.5:35b",
    temperature=0,
    num_ctx=49152,
    num_predict=32768,
)

# LLM의 실제 설정값 확인
print("=== ChatOllama 내부 설정 ===")
for attr in ['num_predict', 'num_ctx', 'model', 'temperature']:
    val = getattr(llm, attr, 'NOT_FOUND')
    print(f"  {attr}: {val}")

# kwargs/options 확인
if hasattr(llm, 'model_kwargs'):
    print(f"  model_kwargs: {llm.model_kwargs}")
if hasattr(llm, '_default_params'):
    print(f"  _default_params: {llm._default_params}")

# 간단한 테스트: 긴 출력을 요청
print("\n=== 테스트: 14개 슬라이더 JSON 생성 ===")
messages = [
    SystemMessage(content="You are a JSON generator. Output ONLY valid JSON, nothing else."),
    HumanMessage(content="""Output a JSON object with exactly 14 slider values.
Use this exact format:
{
  "slider_displace": 0.35,
  "slider_length": 0.40,
  "slider_width": 0.40,
  "slider_weight": 0.35,
  "slider_rpm": 0.30,
  "slider_torq": 0.40,
  "slider_eco": 0.50,
  "slider_materials": 0.45,
  "slider_techniques": 0.45,
  "slider_tech": 0.45,
  "slider_compoenents": 0.45,
  "slider_designperformance": 0.35,
  "slider_designfueleco": 0.50,
  "slider_designdependability": 0.55
}
Just copy and output the above JSON. Nothing else."""),
]

response = llm.invoke(messages)
raw = response.content or ""
print(f"  raw length: {len(raw)} chars")
print(f"  raw content:\n{raw}")

# 메타데이터 전체 덤프
print(f"\n=== response_metadata ===")
meta = getattr(response, 'response_metadata', {})
for k, v in meta.items():
    print(f"  {k}: {v}")

# thinking 필드 확인
print(f"\n=== thinking 필드 확인 ===")
if hasattr(response, 'thinking'):
    print(f"  thinking: {response.thinking[:200] if response.thinking else 'None'}")
else:
    print("  'thinking' attribute: NOT FOUND")

# additional_kwargs 확인
if hasattr(response, 'additional_kwargs'):
    print(f"  additional_kwargs: {response.additional_kwargs}")

# raw 안에 <think> 태그가 있는지
if '<think>' in raw:
    print(f"  <think> tag found in content (len of think block: {raw.find('</think>') - raw.find('<think>')})")
else:
    print("  No <think> tag in content")
