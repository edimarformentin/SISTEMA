from sqlalchemy import (Column, Integer, String, ForeignKey, Boolean, UniqueConstraint)
from sqlalchemy.orm import relationship, declarative_base

Base = declarative_base()

class Cliente(Base):
    __tablename__ = 'clientes'
    id = Column(Integer, primary_key=True, index=True)
    unique_id = Column(String(20), nullable=False, unique=True, index=True)
    nome = Column(String, nullable=False)
    cpf = Column(String, nullable=False, unique=True)
    endereco = Column(String, nullable=False)
    cep = Column(String, nullable=False)
    email = Column(String, nullable=False, unique=True)
    telefone = Column(String, nullable=False)
    ativo = Column(Boolean, default=True)

    frigate_port = Column(Integer, nullable=True, unique=True)
    frigate_container_status = Column(String(50), nullable=True, default='nao_criado')

    cameras = relationship("Camera", back_populates="cliente", cascade="all, delete-orphan")
    __table_args__ = (UniqueConstraint('frigate_port', name='uq_frigate_port'),)

class Camera(Base):
    __tablename__ = 'cameras'
    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(50), nullable=False)
    resolucao = Column(String, nullable=False)
    dias_armazenamento = Column(Integer, nullable=False, default=3) # Para gravação contínua
    observacao = Column(String(100), nullable=True)
    cliente_id = Column(Integer, ForeignKey('clientes.id'))
    ativa = Column(Boolean, default=True)

    # --- Configurações de IA e Gravação ---
    detect_enabled = Column(Boolean, default=True)
    objects_to_track = Column(String(255), default='person,car')
    record_enabled = Column(Boolean, default=True)
    motion_threshold = Column(Integer, default=25)
    ia_fps = Column(Integer, nullable=False, default=15)

    # NOVO CAMPO PARA RETENÇÃO DE EVENTOS DE IA
    ia_event_retention_days = Column(Integer, nullable=False, default=7)

    cliente = relationship("Cliente", back_populates="cameras")
