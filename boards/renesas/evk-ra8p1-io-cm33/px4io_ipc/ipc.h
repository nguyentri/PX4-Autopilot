#pragma once

#include <stdint.h>
#include <stddef.h>

void ipc_init(void);
bool ipc_write(const void *data, size_t len);
bool ipc_read(void *data, size_t len);
uint32_t ipc_available(void);
