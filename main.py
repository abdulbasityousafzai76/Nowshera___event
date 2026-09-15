"""Nowshera Events Co. — Python FastAPI application.
All private requests validate Supabase identity; database functions enforce
ownership, trusted administrator membership and atomic seat allocation.
"""
import os
import csv
import io
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Literal
from uuid import UUID
import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ConfigDict, field_validator

ROOT = Path(__file__).resolve().parent.parent
URL = os.getenv('SUPABASE_URL', 'https://irtjdbkeugbcphdipswb.supabase.co').rstrip('/')
KEY = os.getenv('SUPABASE_PUBLISHABLE_KEY', 'sb_publishable_NUSI3o4WZGHwQkuHt3Anig_-CyQnmZ8')

@asynccontextmanager
async def lifespan(app):
    async with httpx.AsyncClient(timeout=20) as client:
        app.state.client = client
        yield

app = FastAPI(title='Nowshera Events Co. API', lifespan=lifespan)
origins = [x.strip() for x in os.getenv('ALLOWED_ORIGINS','').split(',') if x.strip()]
if origins:
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=['GET','POST'], allow_headers=['Authorization','Content-Type'])

class Credentials(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(default='', max_length=100)
    @field_validator('email')
    @classmethod
    def email_shape(cls, v):
        if v.count('@') != 1 or '.' not in v.rsplit('@',1)[-1] or any(c.isspace() for c in v):
            raise ValueError('Enter a valid email address')
        return v.strip().lower()

class EventInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: UUID | None = None
    title: str = Field(min_length=3,max_length=160)
    description: str = Field(min_length=10,max_length=10000)
    venue: str = Field(min_length=3,max_length=240)
    category: Literal['Workshop','Seminar','Community']
    starts_at: datetime
    capacity: int = Field(ge=1,le=100000,strict=True)
    status: Literal['draft','published','cancelled','completed']
    @field_validator('starts_at')
    @classmethod
    def timezone_required(cls, v):
        if v.tzinfo is None: raise ValueError('A timezone is required')
        return v
    @field_validator('title','description','venue')
    @classmethod
    def trim_text(cls,v):
        if not v.strip(): raise ValueError('This field cannot be blank')
        return v.strip()

async def upstream(request, path, method='POST', data=None, token=None):
    headers={'apikey':KEY,'Content-Type':'application/json'}
    if token: headers['Authorization']='Bearer '+token
    try:
        res=await request.app.state.client.request(method,URL+path,json=data,headers=headers)
    except httpx.RequestError:
        raise HTTPException(503,'Unable to reach the event service. Please try again.')
    if res.is_error:
        try: body=res.json()
        except ValueError: body={}
        message=body.get('msg') or body.get('message') or body.get('error_description') or 'Request could not be completed'
        if body.get('code') in ('23514','22P02','23502'): message='Please check the event fields and try again'
        raise HTTPException(res.status_code if res.status_code in (400,401,403,409,422,429) else 400,message)
    return res.json() if res.content else {}

def bearer(request):
    auth=request.headers.get('Authorization','')
    if not auth.startswith('Bearer '): raise HTTPException(401,'Please sign in to continue')
    return auth[7:]

async def identity(request):
    token=bearer(request)
    user=await upstream(request,'/auth/v1/user','GET',token=token)
    if not user.get('id'): raise HTTPException(401,'Please sign in again')
    return token

async def rpc(request,operation,payload=None,token=None):
    return await upstream(request,'/rest/v1/rpc/nec_api',data={'operation':operation,'payload':payload or {}},token=token)

async def administrator(request):
    token=await identity(request)
    role=await rpc(request,'me',token=token)
    if not role.get('is_admin'): raise HTTPException(403,'Administrator access required')
    return token

@app.middleware('http')
async def security_headers(request,call_next):
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='strict-origin-when-cross-origin'
    response.headers['X-Frame-Options']='DENY'
    if request.url.path.startswith('/api'): response.headers['Cache-Control']='no-store'
    return response

@app.get('/api/health')
async def health(): return {'status':'ok','backend':'python'}

@app.post('/api/auth/signup')
async def signup(body:Credentials,request:Request):
    return await upstream(request,'/auth/v1/signup',data={'email':body.email,'password':body.password,'data':{'name':body.name}})

@app.post('/api/auth/login')
async def login(body:Credentials,request:Request):
    return await upstream(request,'/auth/v1/token?grant_type=password',data={'email':body.email,'password':body.password})

class Refresh(BaseModel):
    refresh_token: str = Field(min_length=1,max_length=4096)
@app.post('/api/auth/refresh')
async def refresh(body:Refresh,request:Request):
    return await upstream(request,'/auth/v1/token?grant_type=refresh_token',data=body.model_dump())

@app.post('/api/auth/logout')
async def logout(request:Request):
    return await upstream(request,'/auth/v1/logout',token=bearer(request))

@app.get('/api/me')
async def me(request:Request): return await rpc(request,'me',token=await identity(request))
@app.get('/api/events')
async def events(request:Request): return await rpc(request,'list')
@app.get('/api/events/{event_id}')
async def detail(event_id:UUID,request:Request): return await rpc(request,'detail',{'id':str(event_id)})
@app.post('/api/events/{event_id}/register')
async def register(event_id:UUID,request:Request): return await rpc(request,'register',{'id':str(event_id)},await identity(request))
@app.get('/api/registrations')
async def registrations(request:Request): return await rpc(request,'my',token=await identity(request))
@app.post('/api/registrations/{registration_id}/cancel')
async def cancel(registration_id:UUID,request:Request): return await rpc(request,'cancel',{'id':str(registration_id)},await identity(request))
@app.get('/api/admin/events')
async def admin_events(request:Request): return await rpc(request,'admin_list',token=await administrator(request))
@app.get('/api/admin/stats')
async def stats(request:Request): return await rpc(request,'stats',token=await administrator(request))
@app.post('/api/admin/events')
async def save(body:EventInput,request:Request): return await rpc(request,'save',body.model_dump(mode='json'),await administrator(request))
@app.post('/api/admin/events/{event_id}/delete')
async def delete(event_id:UUID,request:Request): return await rpc(request,'delete',{'id':str(event_id)},await administrator(request))
@app.get('/api/admin/events/{event_id}/attendees')
async def attendees(event_id:UUID,request:Request): return await rpc(request,'attendees',{'id':str(event_id)},await administrator(request))

def safe_csv(value):
    text=str(value or '')
    return "'"+text if text.lstrip().startswith(('=','+','-','@','\t','\r')) else text

@app.get('/api/admin/events/{event_id}/export')
async def export(event_id:UUID,request:Request):
    rows=await rpc(request,'attendees',{'id':str(event_id)},await administrator(request))
    out=io.StringIO(); writer=csv.writer(out)
    writer.writerow(['Registration ID','Name','Email','Status','Registered at'])
    for row in rows: writer.writerow([safe_csv(row[k]) for k in ('id','name','email','status','created_at')])
    return Response('\ufeff'+out.getvalue(),media_type='text/csv',headers={'Content-Disposition':'attachment; filename="attendees.csv"'})

app.mount('/assets',StaticFiles(directory=ROOT/'dist'/'assets'),name='assets')
@app.get('/{path:path}')
async def frontend(path:str):
    if path.startswith('api/'): raise HTTPException(404,'Not found')
    return FileResponse(ROOT/'dist'/'index.html')
