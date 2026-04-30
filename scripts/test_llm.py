"""
测试千问 LLM 连接
"""
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage

from app.utils.llm_factory import build_chat_model

load_dotenv()


def test_qwen_connection():
    """测试千问模型连接"""

    print("测试千问模型连接...")

    try:
        # 初始化模型
        model = build_chat_model(model="qwen3.6-plus", temperature=0.7)

        # 发送测试消息
        response = model.invoke([
            HumanMessage(content="你好，请用一句话介绍你自己。")
        ])

        print(f"✅ 连接成功！模型回复：\n{response.content}")

    except Exception as e:
        print(f"❌ 连接失败：{e}")
        raise


if __name__ == "__main__":
    test_qwen_connection()
