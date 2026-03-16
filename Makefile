# YouTube Telegram Bot - Makefile

.PHONY: help install test build deploy local clean

# Default target
help: ## Show this help message
	@echo "YouTube Telegram Bot - Available Commands:"
	@echo "=========================================="
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## Install dependencies
	@echo "📦 Installing dependencies..."
	pip install -r requirements.txt

test: ## Test the bot locally
	@echo "🧪 Testing bot functionality..."
	python -c "import yt_dlp; print('yt-dlp version:', yt_dlp.version.__version__)"
	python -c "import telegram; print('python-telegram-bot imported successfully')"
	python -m py_compile telegram_bot_fixed.py
	python -m py_compile telegram_bot_shell.py
	@echo "✅ Tests passed!"

build: ## Build Docker image locally
	@echo "🐳 Building Docker image..."
	docker build -t youtube-telegram-bot .

run-local: ## Run bot locally with Docker
	@echo "🚀 Starting bot locally..."
	docker-compose up --build

run-dev: ## Run bot in development mode (polling)
	@echo "🔧 Starting bot in development mode..."
	python telegram_bot_fixed.py

deploy: ## Deploy to Render
	@echo "🚀 Deploying to Render..."
	./deploy.sh

clean: ## Clean up temporary files
	@echo "🧹 Cleaning up..."
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -exec rm -rf {} +
	docker system prune -f

check: ## Check system dependencies
	@echo "🔍 Checking system dependencies..."
	@which python3 > /dev/null && echo "✅ Python3 found" || echo "❌ Python3 not found"
	@which docker > /dev/null && echo "✅ Docker found" || echo "❌ Docker not found"
	@which git > /dev/null && echo "✅ Git found" || echo "❌ Git not found"
	@which node > /dev/null && echo "✅ Node.js found" || echo "❌ Node.js not found"
	@which ffmpeg > /dev/null && echo "✅ FFmpeg found" || echo "❌ FFmpeg not found"

setup: ## Setup environment for development
	@echo "⚙️  Setting up development environment..."
	@if [ ! -f .env ]; then \
		echo "📝 Creating .env file from template..."; \
		cp .env.template .env; \
		echo "⚠️  Please edit .env file with your settings"; \
	else \
		echo "✅ .env file already exists"; \
	fi
	make install
	make check

logs: ## Show Docker logs
	@echo "📋 Showing Docker logs..."
	docker-compose logs -f

stop: ## Stop local services
	@echo "🛑 Stopping services..."
	docker-compose down

# Development shortcuts
dev: setup run-dev ## Setup and run in development mode
prod: build deploy ## Build and deploy to production

# Default target when no target is specified
.DEFAULT_GOAL := help