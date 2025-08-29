# Nome do arquivo: popular_dados.py
# Função: Insere um cliente e câmeras padrão no banco de dados para testes.

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from models import Base, Cliente, Camera

DATABASE_URL = "postgresql://monitoramento:senha_super_segura@banco:5432/monitoramento"
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

DADOS_CLIENTE = {
    "id": 1, "unique_id": "edimar-rdk18", "nome": "Edimar Formentin",
    "cpf": "075754540977", "email": "edimar.formentin@unifique.com.br",
    "endereco": "Beco São Gabriel, 69", "cep": "89160-000", "telefone": "(47) 99999-9999"
}

OBJETOS_PADRAO = "person,car,dog,cat,bicycle,motorcycle"
RETENCAO_PADRAO = 7 # Dias

DADOS_CAMERAS = [
    {
        "nome": "cam1", "resolucao": "HD", "observacao": "CAMERA 1",
        "dias_armazenamento": 3, "record_enabled": True, "detect_enabled": True,
        "ia_fps": 15, "objects_to_track": OBJETOS_PADRAO, "motion_threshold": 25,
        "ia_event_retention_days": RETENCAO_PADRAO
    },
    {
        "nome": "cam2", "resolucao": "HD", "observacao": "CAMERA 2",
        "dias_armazenamento": 3, "record_enabled": True, "detect_enabled": True,
        "ia_fps": 15, "objects_to_track": OBJETOS_PADRAO, "motion_threshold": 25,
        "ia_event_retention_days": RETENCAO_PADRAO
    },
    {
        "nome": "cam3", "resolucao": "HD", "observacao": "CAMERA 3",
        "dias_armazenamento": 3, "record_enabled": True, "detect_enabled": True,
        "ia_fps": 15, "objects_to_track": OBJETOS_PADRAO, "motion_threshold": 25,
        "ia_event_retention_days": RETENCAO_PADRAO
    },
    {
        "nome": "cam4", "resolucao": "HD", "observacao": "CAMERA 4",
        "dias_armazenamento": 3, "record_enabled": True, "detect_enabled": True,
        "ia_fps": 15, "objects_to_track": OBJETOS_PADRAO, "motion_threshold": 25,
        "ia_event_retention_days": RETENCAO_PADRAO
    },
]

def popular_banco():
    db = SessionLocal()
    try:
        Base.metadata.create_all(bind=engine)
        if db.query(Cliente).filter(Cliente.id == DADOS_CLIENTE["id"]).first():
            print("Cliente de exemplo já existe. Nada a fazer.")
            return

        cliente = Cliente(**DADOS_CLIENTE)
        db.add(cliente)
        db.flush()

        for cam_data in DADOS_CAMERAS:
            db.add(Camera(cliente_id=cliente.id, **cam_data))

        db.execute(text("SELECT setval('clientes_id_seq', (SELECT MAX(id) FROM clientes));"))
        db.execute(text("SELECT setval('cameras_id_seq', (SELECT MAX(id) FROM cameras));"))

        db.commit()
        print("Dados iniciais (cliente e câmeras) inseridos com a nova configuração padrão.")
    except Exception as e:
        print(f"Ocorreu um erro ao tentar popular o banco de dados: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    print("Iniciando script para popular o banco de dados...")
    popular_banco()
