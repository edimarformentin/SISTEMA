import os, random, string, re, unidecode, subprocess, asyncio, json, httpx
from typing import List, Optional
from datetime import datetime
from fastapi import FastAPI, Depends, HTTPException, Form, status, WebSocket, Request, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import sessionmaker, Session, joinedload
from sqlalchemy.exc import IntegrityError
from sqlalchemy import create_engine
from jinja2 import Environment, FileSystemLoader
from starlette.exceptions import HTTPException as StarletteHTTPException
from config.settings import settings
from models import Base, Cliente, Camera

MANAGE_FRIGATE_SCRIPT = "/code/gerenciar_frigate.py"
MANAGE_YOLO_SCRIPT = "/code/gerenciar_yolo.py"
EVENT_CLEANER_SCRIPT = "/home/edimar/SISTEMA/GESTAO_WEB/core_scripts/event_cleaner_host.py" # NOVO CAMINHO NO HOST

engine = create_engine(settings.database_url  )
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
app = FastAPI(title=settings.app_title, version=settings.app_version)
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/media_files", StaticFiles(directory="media_files"), name="media_files")
templates = Environment(loader=FileSystemLoader("templates"))
http_client = httpx.AsyncClient(  )

def sensitivity_filter(value): return {50: 'Baixa', 25: 'Média', 10: 'Alta'}.get(value, 'Desconhecida')
templates.filters['sensitivity'] = sensitivity_filter

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

@app.on_event("startup")
def on_startup(): Base.metadata.create_all(bind=engine)

def trigger_event_cleanup(camera_id: int):
    try:
        command = ["sudo", "-u", "edimar", "python3", EVENT_CLEANER_SCRIPT, "--camera-id", str(camera_id)]
        subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        print(f"INFO: Limpeza de eventos iniciada para a câmera ID {camera_id}.")
    except Exception as e:
        print(f"ERRO: Falha ao iniciar a limpeza de eventos para a câmera ID {camera_id}: {e}")

def get_status_details(cliente_id: int) -> dict:
    db = SessionLocal()
    cliente = db.query(Cliente).filter(Cliente.id == cliente_id).first()
    db.close()
    if not cliente: return {"status": "nao_encontrado", "frigate_port": None}
    if cliente.frigate_container_status == 'pendente': return {"status": "pendente", "frigate_port": cliente.frigate_port}
    if not cliente.frigate_port: return {"status": "nao_criado", "frigate_port": None}
    try:
        result = subprocess.run(["python3", MANAGE_FRIGATE_SCRIPT, "status", str(cliente_id)], capture_output=True, text=True, check=True, timeout=10)
        status_data = json.loads(result.stdout.strip())
        status_data['frigate_port'] = cliente.frigate_port
        return status_data
    except Exception: return {"status": "nao_criado", "frigate_port": cliente.frigate_port}

@app.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    return templates.get_template("home.html").render(request=request, clientes=db.query(Cliente).filter(Cliente.ativo == True).all())

@app.get("/novo_cliente", response_class=HTMLResponse)
def form_novo_cliente(request: Request):
    return templates.get_template("novo_cliente.html").render(request=request)

@app.post("/novo_cliente", response_class=HTMLResponse)
def criar_cliente(request: Request, db: Session = Depends(get_db), nome: str = Form(...), cpf: str = Form(...), email: str = Form(...), telefone: str = Form(...), cep: str = Form(...), endereco: str = Form(...)):
    base = unidecode.unidecode(nome.split()[0].lower()); base = re.sub(r'[^a-z0-9]', '', base)[:10] or 'cliente'
    while True:
        unique_id = f"{base}-{''.join(random.choices(string.ascii_lowercase + string.digits, k=5))}"
        if not db.query(Cliente).filter(Cliente.unique_id == unique_id).first(): break
    novo_cliente = Cliente(unique_id=unique_id, nome=nome, cpf=re.sub(r'[^0-9]', '', cpf), email=email, telefone=telefone, cep=cep, endereco=endereco)
    try:
        db.add(novo_cliente); db.commit(); db.refresh(novo_cliente)
        return RedirectResponse(url=f"/cliente/{novo_cliente.id}", status_code=status.HTTP_303_SEE_OTHER)
    except IntegrityError:
        db.rollback()
        error_message = "Erro: CPF ou E-mail já cadastrados."
        return templates.get_template("novo_cliente.html").render({"request": request, "error": error_message, "form_data": { "nome": nome, "cpf": cpf, "email": email, "telefone": telefone, "cep": cep, "endereco": endereco }})

@app.get("/cliente/{cliente_id}", response_class=HTMLResponse)
def ver_cliente(cliente_id: int, request: Request, db: Session = Depends(get_db)):
    cliente = db.query(Cliente).options(joinedload(Cliente.cameras)).filter(Cliente.id == cliente_id).first()
    if not cliente: raise HTTPException(status_code=404, detail=f"Cliente com ID {cliente_id} não encontrado.")
    existing_cam_names = {cam.nome for cam in cliente.cameras}; i = 1
    while True:
        suggested_name = f"cam{i}"
        if suggested_name not in existing_cam_names: break
        i += 1
    return templates.get_template("ver_cliente.html").render(request=request, cliente=cliente, suggested_cam_name=suggested_name)

@app.get("/cliente/{cliente_id}/status", response_class=JSONResponse)
def get_cliente_status(cliente_id: int):
    return get_status_details(cliente_id)

@app.post("/cliente/{cliente_id}/excluir", response_class=RedirectResponse)
def excluir_cliente(cliente_id: int, db: Session = Depends(get_db)):
    cliente = db.query(Cliente).filter(Cliente.id == cliente_id).first()
    if not cliente: raise HTTPException(404, "Cliente não encontrado")
    try: subprocess.run(["python3", MANAGE_FRIGATE_SCRIPT, "remover", str(cliente.id)], check=True, timeout=90)
    except Exception as e: print(f"AVISO: Script de remoção do Frigate falhou: {e}")
    try: subprocess.run(["python3", MANAGE_YOLO_SCRIPT, "remover-cliente", str(cliente.id)], check=True, timeout=180)
    except Exception as e: print(f"AVISO: Script de remoção do YOLO falhou: {e}")
    db.delete(cliente); db.commit()
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/cliente/{cliente_id}/add_camera", response_class=RedirectResponse)
def add_camera(cliente_id: int, db: Session = Depends(get_db), nome: str = Form(...), resolucao: str = Form(...), dias_armazenamento: int = Form(...), observacao: str = Form(""), record_enabled: Optional[bool] = Form(None), detect_enabled: Optional[bool] = Form(None), detection_type: str = Form(...), objects_to_track: List[str] = Form(default=[]), motion_sensitivity: str = Form("medio"), ia_fps: int = Form(15), ia_event_retention_days: int = Form(7)):
    sensitivity_map = {"baixo": 50, "medio": 25, "alto": 10}
    objects_str = "padrao"
    if detection_type == 'objetos' and objects_to_track: objects_str = ",".join(objects_to_track)

    nova_camera = Camera(
        cliente_id=cliente_id, nome=nome, resolucao=resolucao,
        dias_armazenamento=dias_armazenamento, observacao=observacao,
        record_enabled=bool(record_enabled), detect_enabled=bool(detect_enabled),
        objects_to_track=objects_str, motion_threshold=sensitivity_map.get(motion_sensitivity, 25),
        ia_fps=ia_fps, ia_event_retention_days=ia_event_retention_days
    )
    db.add(nova_camera)
    cliente = db.query(Cliente).filter(Cliente.id == cliente_id).first()
    if cliente: cliente.frigate_container_status = 'pendente'
    db.commit()
    return RedirectResponse(url=f"/cliente/{cliente_id}", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/camera/{camera_id}/excluir", response_class=RedirectResponse)
def excluir_camera(camera_id: int, db: Session = Depends(get_db)):
    camera = db.query(Camera).filter(Camera.id == camera_id).first()
    if not camera: raise HTTPException(404, "Câmera não encontrada")
    cliente_id = camera.cliente_id
    try: subprocess.run(["python3", MANAGE_YOLO_SCRIPT, "remover-camera", str(camera.id)], check=True, timeout=60)
    except Exception as e: print(f"AVISO: Script de remoção do YOLO falhou: {e}")
    db.delete(camera); db.commit()

    if db.query(Camera).filter(Camera.cliente_id == cliente_id).count() == 0:
        try: subprocess.run(["python3", MANAGE_FRIGATE_SCRIPT, "remover", str(cliente_id)], check=True, timeout=90)
        except Exception as e: print(f"AVISO: Script de remoção do Frigate falhou: {e}")
    else:
        cliente = db.query(Cliente).filter(Cliente.id == cliente_id).first()
        if cliente: cliente.frigate_container_status = 'pendente'; db.commit()

    return RedirectResponse(url=f"/cliente/{cliente_id}", status_code=status.HTTP_303_SEE_OTHER)

@app.websocket("/ws/frigate_manage/{cliente_id}")
async def websocket_manage_frigate(websocket: WebSocket, cliente_id: int):
    await websocket.accept()
    db = SessionLocal()
    try:
        await websocket.send_text(">>> Sincronizando Gravação (Frigate)...\n")
        p_frigate = await asyncio.create_subprocess_exec("python3", MANAGE_FRIGATE_SCRIPT, "criar", str(cliente_id), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        async for line in p_frigate.stdout: await websocket.send_text(line.decode())
        async for line in p_frigate.stderr: await websocket.send_text(f"ERRO: {line.decode()}")
        await p_frigate.wait()

        await websocket.send_text("\n>>> Sincronizando Detectores de IA (YOLO)...\n")
        cliente = db.query(Cliente).options(joinedload(Cliente.cameras)).filter(Cliente.id == cliente_id).first()
        if cliente and cliente.cameras:
            for cam in cliente.cameras:
                await websocket.send_text(f"--> Processando câmera: {cam.nome}\n")
                p_yolo = await asyncio.create_subprocess_exec("python3", MANAGE_YOLO_SCRIPT, "criar-atualizar", str(cam.id), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                async for line in p_yolo.stdout: await websocket.send_text(f"    {line.decode()}")
                async for line in p_yolo.stderr: await websocket.send_text(f"    ERRO: {line.decode()}")
                await p_yolo.wait()
        await websocket.send_text("\n>>> Sincronização Concluída.")
    except Exception as e: await websocket.send_text(f"\n>>> Erro geral: {str(e)}")
    finally:
        db.close()
        await websocket.send_text("\n<<<<<PROCESS_COMPLETE>>>>>")
        await websocket.close()

@app.get("/cliente/{cliente_id}/editar", response_class=HTMLResponse)
def form_editar_cliente(cliente_id: int, request: Request, db: Session = Depends(get_db)):
    cliente = db.query(Cliente).filter(Cliente.id == cliente_id).first()
    if not cliente: raise HTTPException(404, "Cliente não encontrado")
    return templates.get_template("editar_cliente.html").render(request=request, cliente=cliente)

@app.post("/cliente/{cliente_id}/editar", response_class=RedirectResponse)
def salvar_cliente_editado(cliente_id: int, db: Session = Depends(get_db), nome: str = Form(...), cpf: str = Form(...), email: str = Form(...), telefone: str = Form(...), cep: str = Form(...), endereco: str = Form(...)):
    cliente = db.query(Cliente).filter(Cliente.id == cliente_id).first()
    if not cliente: raise HTTPException(404, "Cliente não encontrado")
    cliente.nome, cliente.cpf, cliente.email, cliente.telefone, cliente.cep, cliente.endereco = nome, re.sub(r'[^0-9]', '', cpf), email, telefone, cep, endereco
    db.commit(); return RedirectResponse(url=f"/cliente/{cliente_id}", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/camera/{camera_id}/editar", response_class=HTMLResponse)
def form_editar_camera(camera_id: int, request: Request, db: Session = Depends(get_db)):
    camera = db.query(Camera).filter(Camera.id == camera_id).first()
    if not camera: raise HTTPException(404, "Câmera não encontrada")
    return templates.get_template("editar_camera.html").render(request=request, camera=camera)

@app.post("/camera/{camera_id}/editar", response_class=RedirectResponse)
def salvar_camera_editada(camera_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db), nome: str = Form(...), resolucao: str = Form(...), dias_armazenamento: int = Form(...), observacao: str = Form(""), record_enabled: Optional[bool] = Form(None), detect_enabled: Optional[bool] = Form(None), detection_type: str = Form(...), objects_to_track: List[str] = Form(default=[]), motion_sensitivity: str = Form("medio"), ia_fps: int = Form(15), ia_event_retention_days: int = Form(7)):
    camera = db.query(Camera).filter(Camera.id == camera_id).first()
    if not camera: raise HTTPException(404, "Câmera não encontrada")

    retention_changed = camera.ia_event_retention_days != ia_event_retention_days

    sensitivity_map = {"baixo": 50, "medio": 25, "alto": 10}
    camera.nome, camera.resolucao, camera.dias_armazenamento, camera.observacao = nome, resolucao, dias_armazenamento, observacao
    camera.record_enabled, camera.detect_enabled = bool(record_enabled), bool(detect_enabled)
    camera.motion_threshold = sensitivity_map.get(motion_sensitivity, 25)
    camera.ia_fps = ia_fps
    camera.ia_event_retention_days = ia_event_retention_days

    camera.objects_to_track = "padrao"
    if detection_type == 'objetos' and objects_to_track: camera.objects_to_track = ",".join(objects_to_track)

    cliente = db.query(Cliente).filter(Cliente.id == camera.cliente_id).first()
    if cliente: cliente.frigate_container_status = 'pendente'
    db.commit()

    if retention_changed:
        background_tasks.add_task(trigger_event_cleanup, camera.id)

    return RedirectResponse(url=f"/cliente/{camera.cliente_id}", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/cliente/{cliente_id}/eventos", response_class=HTMLResponse)
def ver_eventos(cliente_id: int, request: Request, db: Session = Depends(get_db)):
    cliente = db.query(Cliente).filter(Cliente.id == cliente_id).first()
    if not cliente: raise HTTPException(status_code=404, detail="Cliente não encontrado")

    eventos_por_camera = {}
    base_event_path = f"/code/media_files/FRIGATE/{cliente.unique_id}/events"

    try:
        from zoneinfo import ZoneInfo
        SAO_PAULO_TZ = ZoneInfo("America/Sao_Paulo")
    except ImportError:
        import pytz
        SAO_PAULO_TZ = pytz.timezone("America/Sao_Paulo")

    if os.path.isdir(base_event_path):
        for cam_dir in sorted(os.listdir(base_event_path)):
            cam_path = os.path.join(base_event_path, cam_dir)
            if os.path.isdir(cam_path):
                eventos = []
                for filename in sorted(os.listdir(cam_path), reverse=True):
                    if filename.lower().endswith((".jpg", ".jpeg", ".png")):
                        try:
                            parts = os.path.splitext(filename)[0].split('_'); ts, hr, obj = parts[0], parts[1], parts[-1]
                            utc_dt = datetime.strptime(f"{ts} {hr}", "%Y%m%d %H%M%S").replace(tzinfo=ZoneInfo("UTC"))
                            sp_dt = utc_dt.astimezone(SAO_PAULO_TZ)
                            eventos.append({
                                "url": f"/media_files/FRIGATE/{cliente.unique_id}/events/{cam_dir}/{filename}",
                                "objeto": obj, "data": sp_dt.strftime("%d/%m/%Y"), "hora": sp_dt.strftime("%H:%M:%S")
                            })
                        except (ValueError, IndexError):
                            eventos.append({"url": f"/media_files/FRIGATE/{cliente.unique_id}/events/{cam_dir}/{filename}", "objeto": "Desconhecido", "data": "N/A", "hora": "N/A"})
                if eventos: eventos_por_camera[cam_dir] = eventos

    return templates.get_template("ver_eventos.html").render(request=request, cliente=cliente, eventos_por_camera=eventos_por_camera)


@app.get("/stream/{unique_id}/{cam_nome_sanitizado}/{filename:path}")
async def stream_proxy(unique_id: str, cam_nome_sanitizado: str, filename: str):
    media_mtx_url = f"http://sistema-mediamtx:8888/live/{unique_id}/{cam_nome_sanitizado}/{filename}"
    try:
        req = http_client.build_request("GET", media_mtx_url  ); r = await http_client.send(req, stream=True  ); r.raise_for_status()
        return StreamingResponse(r.aiter_bytes(), status_code=r.status_code, headers=r.headers)
    except httpx.RequestError as e: raise HTTPException(status_code=502, detail=f"Não foi possível conectar ao MediaMTX: {e}"  )

@app.get("/api/buscar_cliente_por_cpf", response_class=JSONResponse)
def api_buscar_cliente_por_cpf(cpf: str, db: Session = Depends(get_db)):
    cliente = db.query(Cliente).filter(Cliente.cpf == re.sub(r'[^0-9]', '', cpf)).first()
    if not cliente: return JSONResponse(status_code=404, content={"detail": "Nenhum cliente encontrado com este CPF."})
    return {"id": cliente.id, "nome": cliente.nome, "cpf": cliente.cpf}

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException  ):
    if exc.status_code == 404:
        return HTMLResponse(content=templates.get_template("erro.html").render({"request": request, "message": exc.detail}), status_code=exc.status_code)
    return JSONResponse(status_code=exc.status_code, content={"detail": f"Ocorreu um erro interno: {exc.detail}"})

# ====== endpoint de health para vídeos de evento ======
try:
    from pathlib import Path
    from fastapi.responses import JSONResponse
except Exception:
    pass
else:
    if 'app' in globals():
        @app.get("/health/event-videos")
        def health_event_videos():
            base = Path("/code/media_files/FRIGATE")
            jpg = mp4 = missing = 0
            if base.exists():
                for p in base.rglob("events/*/*.jpg"):
                    jpg += 1
                    if not p.with_suffix(".mp4").exists():
                        missing += 1
                for _ in base.rglob("events/*/*.mp4"):
                    mp4 += 1
            return JSONResponse({
                "ok": True,
                "base": str(base),
                "jpg": jpg,
                "mp4": mp4,
                "missing": missing
            })
# ====== fim endpoint ======

# ====== endpoint utilitário: descobrir vídeo de um snapshot (.mp4 exato ou *_merged.mp4) ======
try:
    import re, os
    from pathlib import Path
    from fastapi import Query
    from fastapi.responses import JSONResponse
except Exception:
    pass
else:
    if 'app' in globals():
        _TS_RE = re.compile(r'(?P<ts>\d{8}_\d{6})')

        def _to_rel_from_frigate(p: str) -> str:
            # aceita urls (/media_files/FRIGATE/... ou /FRIGATE/...), caminho host (/home/.../FRIGATE/...), ou relativo
            p = p.strip()
            if p.startswith("http://") or p.startswith("https://"):
                try:
                    from urllib.parse import urlparse
                    u = urlparse(p)
                    p = u.path
                except Exception:
                    pass
            if p.startswith("/media_files/FRIGATE/"):
                return p[len("/media_files/FRIGATE/"):]
            if p.startswith("/FRIGATE/"):
                return p[len("/FRIGATE/"):]
            if "/FRIGATE/" in p:
                return p.split("/FRIGATE/",1)[1]
            return p.lstrip("/")

        @app.get("/api/event-video")
        def api_event_video(jpg: str = Query(..., description="caminho do .jpg (url ou fs)")):
            base = Path("/code/media_files/FRIGATE").resolve()
            rel = _to_rel_from_frigate(jpg)
            fs_jpg = (base / rel).resolve()

            # segurança: precisa estar dentro de base
            if not str(fs_jpg).startswith(str(base)):
                return JSONResponse({"ok": False, "error": "forbidden"}, status_code=403)

            if not fs_jpg.exists():
                return JSONResponse({"ok": False, "error": "jpg_not_found", "path": f"/media_files/FRIGATE/{rel}"}, status_code=404)

            tried = []
            # 1) .mp4 exato
            mp4_exact = fs_jpg.with_suffix(".mp4")
            tried.append(str(mp4_exact))
            if mp4_exact.exists():
                url = "/media_files/FRIGATE/" + os.path.relpath(mp4_exact, base)
                return JSONResponse({"ok": True, "url": url, "mode": "exact", "tried": tried})

            # 2) procurar *_merged.mp4 com mesmo timestamp inicial
            m = _TS_RE.search(fs_jpg.name)
            if m:
                ts = m.group("ts")
                dirp = fs_jpg.parent
                candidates = sorted(dirp.glob(f"{ts}__*_merged.mp4"))
                for c in candidates:
                    tried.append(str(c))
                    if c.exists():
                        url = "/media_files/FRIGATE/" + os.path.relpath(c, base)
                        return JSONResponse({"ok": True, "url": url, "mode": "merged", "tried": tried})

            return JSONResponse({"ok": False, "error": "video_not_found", "tried": tried}, status_code=404)
# ====== fim endpoint utilitário ======
