# Guia Acadêmico IA

Assistente que responde dúvidas sobre as normas da graduação (UFU e UNIUBE) com base nos documentos oficiais, sempre citando o artigo e a página de origem. Quando a norma não cobre a pergunta, ele avisa em vez de inventar.

> **Status:** em desenvolvimento. Este repositório é um projeto de portfólio e **não é um canal oficial** de nenhuma das instituições. Confirme sempre a informação na fonte citada.

## Por que existe

As regras de trancamento, aproveitamento de estudos, horas complementares, estágio e TCC ficam espalhadas em PDFs longos. Estudantes perdem tempo procurando, ou decidem com informação errada.

## Como vai funcionar

1. Os documentos oficiais são divididos por artigo e guardados no PostgreSQL (pgvector).
2. A pergunta é convertida em embedding e os trechos mais relevantes são recuperados.
3. O modelo responde somente com base nesses trechos e cita a fonte.
4. Se nada relevante for encontrado, o sistema recusa a resposta.

## Avaliação

Um conjunto de perguntas reais, com a resposta e a fonte esperadas, mede:

- se o trecho correto foi recuperado;
- se a resposta está correta;
- se o sistema recusa perguntas fora do escopo.

Cada mudança (tamanho de chunk, reranking, prompt) será registrada com o efeito nessas métricas.

## Stack

Python, uv, FastAPI, PostgreSQL + pgvector, Docker. Frontend em React (fase posterior).

## Dados

Os PDFs **não são versionados** neste repositório. Os links das fontes públicas estão em [SOURCES.md](SOURCES.md), e um script baixa os arquivos para `data/raw/`.

## Roadmap

- [x] Estrutura do projeto e ambiente
- [ ] Coleta e ingestão dos documentos (divisão por artigo)
- [ ] RAG de ponta a ponta com citação de fonte
- [ ] Conjunto de avaliação e métricas
- [ ] Melhorias medidas (chunking, reranking, prompt)
- [ ] API, frontend e deploy público
- [ ] Observabilidade (custo e latência por pergunta)

## Licença

MIT