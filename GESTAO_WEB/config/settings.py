from pydantic_settings import BaseSettings

# Define uma classe de configurações que carrega variáveis do ambiente.
# Isso centraliza a configuração e evita hardcoding de senhas e outros dados.
class Settings(BaseSettings):
    # Variáveis do banco de dados
    postgres_user: str = "monitoramento"
    postgres_password: str = "senha_super_segura"
    postgres_db: str = "monitoramento"
    postgres_host: str = "banco"
    postgres_port: int = 5432

    # Metadados da aplicação
    app_title: str = "Sistema de Monitoramento"
    app_version: str = "3.0.0"

    class Config:
        # Define o arquivo .env como fonte das variáveis de ambiente.
        env_file = ".env"

    # Propriedade computada para construir a URL de conexão com o banco de dados.
    @property
    def database_url(self) -> str:
        return f"postgresql://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"

# Cria uma instância global das configurações para ser importada em outros módulos.
settings = Settings()
