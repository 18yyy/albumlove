# Editor de Álbum Personalizado

Aplicação local para editar PDFs de figurinhas e álbum do Dia dos Namorados usando os modelos que já estão na pasta do projeto.

## Como rodar

```powershell
python app.py
```

Abra:

```text
http://127.0.0.1:8000
```

O projeto usa `PyMuPDF` e `Pillow`. Eles já estão instalados neste ambiente. Em outro computador:

```powershell
pip install -r requirements.txt
```

## Hospedar na Netlify com senha

O projeto já inclui:

- `netlify.toml`
- `netlify/edge-functions/auth.js`
- `static/login.html`

Na Netlify, configure estas variáveis em `Site configuration > Environment variables`:

```text
ACCESS_PASSWORD=sua-senha-aqui
ACCESS_SESSION_SECRET=um-token-grande-e-aleatorio
BACKEND_ORIGIN=https://url-do-seu-backend-python
```

Não coloque a senha dentro do HTML, JavaScript ou GitHub. A senha fica escondida nas variáveis da Netlify e a Edge Function libera o site usando cookie `HttpOnly`.

Importante: a Netlify hospeda bem o frontend, mas não roda este backend Python/PyMuPDF como servidor permanente. Para usar geração e preview de PDF online, hospede `app.py` em um serviço Python como Render, Railway, Fly.io ou VPS, e coloque a URL em `BACKEND_ORIGIN`.

Se você quiser só testar a tela protegida na Netlify, `BACKEND_ORIGIN` pode ficar vazio, mas os botões que usam `/api` não funcionarão até existir um backend.

## Multiusuário

O backend cria uma sessão isolada por navegador usando cookie `album_editor_session`.

Cada sessão tem seus próprios arquivos em:

```text
sessions/<id-da-sessao>/
```

Dentro dela ficam:

- `photos/`: fotos enviadas por aquele usuário.
- `template.json`: template editado por aquele usuário.
- `output/`: PDFs e ZIP gerados por aquele usuário.

Isso evita conflito entre usuários usando o site ao mesmo tempo. Se a pessoa enviar fotos pelo campo `Enviar fotos desta sessão`, o sistema usa essas fotos no preview e na geração. Se não enviar, usa a pasta padrão `fotos/`.

Em hospedagem cloud, prefira disco persistente ou armazenamento externo se você quiser manter sessões por muito tempo. Em serviços com disco temporário, as sessões podem sumir em redeploy/restart.

## Rodar local com senha

No PowerShell, rode assim:

```powershell
$env:ACCESS_PASSWORD="sua-senha-aqui"
$env:ACCESS_SESSION_SECRET="um-token-grande-e-aleatorio"
python app.py
```

Se `ACCESS_PASSWORD` não estiver configurada, o servidor local abre sem senha.

## Arquivos esperados

- `Figurinhas.pdf`
- `Álbum Oficial - Nosso Amor.pdf`
- `fotos/` com as fotos do cliente

## Fluxo

1. Abra o site local.
2. Confirme os caminhos dos PDFs e da pasta `fotos`.
3. Preencha nomes, data e texto.
4. Clique em `Analisar PDFs`.
5. Ajuste as caixas no preview. As caixas podem ser arrastadas e redimensionadas.
6. Use a alça acima da caixa para girar o campo, ou os botões de rotação na barra superior.
7. Use o painel lateral para alterar tipo, página, coordenadas, rotação, fonte, cor, fundo, alinhamento e número da foto.
8. Para campos de texto, escolha se o fundo deve cobrir a área antiga ou ficar transparente.
9. Use `Capturar fundo original` para tentar pegar uma cor próxima do fundo do PDF ao redor do campo.
10. O preview mostra fotos, nomes, datas e textos em tempo real por cima do PDF.
11. Em campos de foto, ajuste `Zoom da foto`, `Crop X`, `Crop Y` e opacidade de edição pelo painel lateral.
12. Apague o campo selecionado com `Del`, `Backspace` ou pelo botão de apagar.
13. Use as setas do teclado para mover o campo selecionado. Com `Shift`, o movimento é maior.
14. No canvas, use o scroll do mouse para dar zoom no ponto onde o cursor está.
15. Use `Shift + scroll` para navegar lateralmente.
16. Arraste com o botão do meio do mouse, ou segure `Espaço` e arraste, para mover pela página como em um editor visual.
17. Clique em `Salvar Template` para gravar `template.json`.
18. Clique em `Gerar PDFs` ou `Gerar PDF Base Editável`.

## Saídas

Os arquivos finais são salvos em `output/`:

- `figurinhas_final.pdf`
- `album_final.pdf`
- `pdfs_final.zip`
- `figurinhas_base_editavel.pdf`
- `album_base_editavel.pdf`
- `pdfs_base_editavel.zip`

## Observação técnica

A análise automática detecta imagens existentes nos PDFs, remove molduras sobrepostas quando encontra uma foto interna mais provável e também tenta criar campos a partir dos textos do modelo. A revisão manual no preview continua sendo importante, principalmente no álbum oficial, para evitar preencher espaços que são só para colagem.
