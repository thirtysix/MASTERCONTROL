.PHONY: dev start stop status restart install install-desktop scan

dev:
	./mastercontrol.sh start --foreground

start:
	./mastercontrol.sh start

stop:
	./mastercontrol.sh stop

status:
	./mastercontrol.sh status

restart:
	./mastercontrol.sh restart

install:
	cd backend && pip install -e '.[dev]'

install-desktop:
	./scripts/install-desktop.sh

scan:
	cd backend && python -m src.cli scan
