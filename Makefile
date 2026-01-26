# MIRS Makefile
# Usage: make <target>

.PHONY: help test test-ota test-api test-all sync run clean

help:
	@echo "MIRS Development Commands"
	@echo ""
	@echo "Testing:"
	@echo "  make test        - Run unit tests"
	@echo "  make test-ota    - Run OTA scheduler tests"
	@echo "  make test-api    - Run API endpoint tests (requires running server)"
	@echo "  make test-all    - Run all tests including API"
	@echo "  make test-json   - Run all tests and output JSON report"
	@echo ""
	@echo "Development:"
	@echo "  make run         - Start development server"
	@echo "  make sync        - Sync files to RPi"
	@echo ""
	@echo "Build:"
	@echo "  make release     - Create release package"
	@echo ""

# Testing
test:
	python tests/run_all_tests.py

test-ota:
	python tests/run_all_tests.py --suite ota

test-api:
	python tests/run_all_tests.py --api-tests

test-all:
	python tests/run_all_tests.py --api-tests

test-json:
	python tests/run_all_tests.py --api-tests --json --output test_report.json

test-e2e:
	python tests/run_all_tests.py --api-tests --output test_report_$(shell date +%Y%m%d_%H%M%S).json

# Development
run:
	MIRS_PORT=8000 python main.py

# Sync to RPi
sync:
	./scripts/sync_to_rpi.sh

# Release
release:
	@echo "Run: ./scripts/create_release.sh <version>"

# Clean
clean:
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	rm -f test_report*.json
