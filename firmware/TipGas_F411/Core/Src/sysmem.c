/* _sbrk para newlib (heap entre _end e a pilha) */
#include <errno.h>
#include <stdint.h>
#include <stddef.h>
extern uint8_t _end, _estack;
extern uint32_t _Min_Stack_Size;
static uint8_t *heap_end = NULL;
void *_sbrk(ptrdiff_t incr)
{
  const uint8_t *max_heap = &_estack - (uint32_t)&_Min_Stack_Size;
  if (heap_end == NULL) heap_end = &_end;
  if (heap_end + incr > max_heap) { errno = ENOMEM; return (void *)-1; }
  uint8_t *prev = heap_end;
  heap_end += incr;
  return prev;
}
