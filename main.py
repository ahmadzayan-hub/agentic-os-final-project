"""Entry point for the Agentic OS application.

Loads the configuration, creates the Agent, and runs the interactive
command-line loop until the user enters /exit.
"""

import sys

from agent import Agent
from utils import load_config

CONFIG_FILE = "config.json"


def main():
    try:
        config = load_config(CONFIG_FILE)
    except FileNotFoundError as error:
        print(f"Error: {error}")
        print("Create config.json in the project folder and try again.")
        return 1
    except ValueError as error:
        print(f"Error: {error}")
        print("Fix the JSON syntax in config.json and try again.")
        return 1

    agent = Agent(config)
    print(agent.get_welcome_message())

    # The prompt labels follow the agent's language, and are re-read each
    # turn because /set language can change it mid-session.
    while True:
        try:
            user_input = input(f"{agent.text('you_label')}: ").strip()
        except (KeyboardInterrupt, EOFError):
            print(f"\n{agent.text('agent_label')}: {agent.text('goodbye')}")
            break

        if not user_input:
            print(f"{agent.text('agent_label')}: {agent.text('empty_input')}")
            continue
        if user_input.split()[0].lower() == "/exit":
            print(f"{agent.text('agent_label')}: {agent.text('goodbye')}")
            break

        response = agent.process_input(user_input)
        print(f"{agent.text('agent_label')}: {response}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
