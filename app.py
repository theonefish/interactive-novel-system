"""CLI 入口 - 交互式小说创作系统"""

import uuid
from langgraph.types import Command

from graph import build_graph
from state import NovelState


def print_banner():
    """打印欢迎横幅"""
    print("=" * 50)
    print("🎬  交互式小说创作系统")
    print("=" * 50)
    print("你扮演主角，AI 担任编剧团队，共同创作你的故事。")
    print("输入 A/B/C 选择选项，或自由输入扮演角色。")
    print("输入「生成全文」或「结束」来完结故事。")
    print("=" * 50)
    print()


def get_initial_input() -> str:
    """获取用户的初始创作需求"""
    print("你想创作一个什么样的故事？")
    print("（例如：末日废土，主角是个带着女儿的父亲）")
    print()
    return input("> ").strip()


def run_session():
    """运行一次交互式小说创作会话"""
    print_banner()

    initial_request = get_initial_input()
    if not initial_request:
        print("输入不能为空，再见。")
        return

    # 构建图
    app = build_graph()

    # 创建会话
    session_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": session_id}}

    # 初始状态
    initial_state: NovelState = {
        "user_request": initial_request,
        "world_setting": "",
        "characters": [],
        "rules": "",
        "setting_confirmed": False,
        "story_segments": [],
        "current_segment": "",
        "plot_version": 0,
        "segment_history": [],
        "current_options": [],
        "user_choices": [],
        "current_turn": 0,
        "awaiting_user": False,
        "critique": "",
        "critique_score": 0,
        "risk_warnings": [],
        "final_output": "",
        "backtrack_message": "",
        "memory": {
            "characters": [],
            "plot_threads": [],
            "foreshadowing": [],
            "timeline": [],
            "world_notes": [],
        },
        "messages": [],
        "current_phase": "init",
        "iteration_count": 0,
        "max_internal_iterations": 3,
    }

    # 首次调用
    try:
        result = app.invoke(initial_state, config)
    except Exception as e:
        print(f"\n❌ 启动失败：{e}")
        return

    # 交互循环
    while True:
        phase = result.get("current_phase", "")

        # 检查是否已完成
        if phase == "done":
            print("\n感谢你的创作！再见。")
            break

        # 检查是否有中断等待（通过 interrupt 的返回值）
        # 如果有 current_segment 且 phase 是 story_progressing，需要用户输入
        if phase == "story_progressing":
            # 展示内容已经在 interrupt 中输出，等待用户输入
            user_input = input("\n> ").strip()
            if not user_input:
                continue

            # 继续执行
            try:
                result = app.invoke(Command(resume=user_input), config)
            except Exception as e:
                print(f"\n❌ 执行出错：{e}")
                break

        elif phase == "world_building":
            # 世界设定阶段，等待用户确认
            user_input = input("\n> ").strip()
            if not user_input:
                user_input = "A"

            try:
                result = app.invoke(Command(resume=user_input), config)
            except Exception as e:
                print(f"\n❌ 执行出错：{e}")
                break

        elif phase == "completed":
            # 整合完成，展示最终输出
            try:
                result = app.invoke(Command(resume=""), config)
            except Exception as e:
                print(f"\n❌ 执行出错：{e}")
                break

        else:
            # 其他情况
            user_input = input("\n> ").strip()
            try:
                result = app.invoke(Command(resume=user_input), config)
            except Exception as e:
                print(f"\n❌ 执行出错：{e}")
                break


def main():
    try:
        run_session()
    except KeyboardInterrupt:
        print("\n\n已退出。下次再见！")
    except Exception as e:
        print(f"\n❌ 发生未预期错误：{e}")


if __name__ == "__main__":
    main()