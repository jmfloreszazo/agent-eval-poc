# Shortcuts for the full PoC cycle.
# Usage: make <target>

AGENT := ../agent
DATA := data/trajectory.json

.PHONY: help phoenix agent deps evals all clean

help:
	@echo "Targets:"
	@echo "  make phoenix   - start self-hosted Phoenix (Docker, :6006)"
	@echo "  make agent     - run the .NET agent and generate $(DATA)"
	@echo "  make deps      - install eval dependencies (Python)"
	@echo "  make evals     - run the DeepEval suite (pytest)"
	@echo "  make all       - agent + evals"
	@echo "  make clean     - clean build artifacts"

phoenix:
	docker run --rm -p 6006:6006 arizephoenix/phoenix:latest

agent:
	dotnet run --project $(AGENT) -c Release -- $(DATA)

deps:
	pip install -r evals/requirements.txt

evals:
	pytest evals/test_agent_trajectory.py -v

all: agent evals

clean:
	rm -rf $(AGENT)/bin $(AGENT)/obj evals/__pycache__ .pytest_cache .deepeval
