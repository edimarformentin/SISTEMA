# Define a imagem base do Python
FROM python:3.11-slim

# Define o diretório de trabalho dentro do contêiner
WORKDIR /code

# Instala dependências do sistema:
# - ca-certificates, curl, gnupg: Para adicionar o repositório do Docker.
# - docker-ce-cli, docker-compose-plugin: Para que o backend possa gerenciar outros contêineres (Frigate).
# - netcat-traditional: Usado pelo script wait-for-it.sh.
RUN apt-get update && \
    apt-get install -y ca-certificates curl gnupg sudo && \
    install -m 0755 -d /etc/apt/keyrings && \
    curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg && \
    chmod a+r /etc/apt/keyrings/docker.gpg && \
    echo \
      "deb [arch=$(dpkg --print-architecture ) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian \
      $(. /etc/os-release && echo "$VERSION_CODENAME" ) stable" | \
      tee /etc/apt/sources.list.d/docker.list > /dev/null && \
    apt-get update && \
    apt-get install -y docker-ce-cli docker-compose-plugin netcat-traditional && \
    rm -rf /var/lib/apt/lists/*

# Copia o arquivo de requisitos para o contêiner
COPY requirements.txt .

# Instala as bibliotecas Python
RUN pip install --no-cache-dir -r requirements.txt

# Copia o restante do código da aplicação
COPY . .

# Baixa e torna executável o script 'wait-for-it'
ADD https://raw.githubusercontent.com/vishnubob/wait-for-it/master/wait-for-it.sh /wait-for-it.sh
RUN chmod +x /wait-for-it.sh

# Garante que a saída do Python não seja bufferizada
ENV PYTHONUNBUFFERED=1

# Expõe a porta que a aplicação usará
EXPOSE 8000

# Comando de inicialização:
# 1. Espera o banco de dados estar pronto na porta 5432.
# 2. Espera o MediaMTX estar pronto na porta 8888.
# 3. Inicia o servidor Uvicorn com reload automático.
CMD ["/wait-for-it.sh", "banco:5432", "--", "/wait-for-it.sh", "sistema-mediamtx:8888", "--", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
