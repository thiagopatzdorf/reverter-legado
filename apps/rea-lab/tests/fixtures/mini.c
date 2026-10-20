// mini.c: amostra no estilo do Doom (K&R com nome na linha seguinte)
#include <stdio.h>
#define MAX(a, b) ((a) > (b) ? (a) : (b))

typedef struct { int x; } ponto_t;
static int tabela[] = { 1, 2, 3 };
static const char *msg = "Wad file %s doesn't have IWAD or PWAD id\n";

static void
P_Interna (int a)
{
    if (a) { printf("dentro {chave} \"aspas\"\n"); }
}

int W_Conta(const char *nome)
{
    /* comentario com { chave } */
    return MAX(1, nome[0] == '{');
}

void (*ponteiro)(void);
