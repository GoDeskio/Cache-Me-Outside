# Top level makefile, the real magic is at src/Makefile

default: all

# Forward every target into src/, then build loadable modules listed for the
# image. `all` is explicit so the module is part of a normal `make`.
all:
	cd src && $(MAKE) all
	$(MAKE) -C modules/timeseries

.DEFAULT:
	cd src && $(MAKE) $@

install:
	cd src && $(MAKE) $@

.PHONY: install
