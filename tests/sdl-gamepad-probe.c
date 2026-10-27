/* Read-only runtime probe for Selkies' SDL-visible virtual gamepad slots. */
#include <stdio.h>

typedef unsigned int Uint32;
extern int SDL_Init(Uint32 flags);
extern void SDL_Quit(void);
extern int SDL_NumJoysticks(void);
extern const char *SDL_JoystickNameForIndex(int device_index);

#define SDL_INIT_JOYSTICK 0x00000200u
#define SDL_INIT_GAMECONTROLLER 0x00002000u

int main(void) {
  if (SDL_Init(SDL_INIT_JOYSTICK | SDL_INIT_GAMECONTROLLER) != 0)
    return 2;
  const int count = SDL_NumJoysticks();
  printf("count=%d\n", count);
  for (int i = 0; i < count; ++i) {
    const char *name = SDL_JoystickNameForIndex(i);
    printf("%d=%s\n", i, name ? name : "<unknown>");
  }
  SDL_Quit();
  return count >= 2 ? 0 : 1;
}
