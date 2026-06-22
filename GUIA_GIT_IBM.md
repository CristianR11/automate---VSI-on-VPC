# Guía para Subir Proyecto a IBM Git (GitLab)

## 📋 Requisitos Previos

1. Tener acceso a IBM GitLab
2. Tener Git instalado en tu máquina
3. Tener configurado tu usuario de Git

## 🔧 Paso 1: Configurar Git (Si no lo has hecho)

```bash
# Configurar tu nombre
git config --global user.name "Tu Nombre"

# Configurar tu email de IBM
git config --global user.email "tu.email@ibm.com"

# Verificar configuración
git config --list
```

## 🔑 Paso 2: Generar Token de Acceso Personal (PAT)

### Opción A: Usar IBM w3id SSO

1. Ve a IBM GitLab: https://github.ibm.com
2. Inicia sesión con tu w3id
3. Ve a tu perfil (esquina superior derecha) → **Settings**
4. En el menú izquierdo: **Access Tokens**
5. Crea un nuevo token:
   - **Name**: `tunal-automation-token`
   - **Expiration date**: Selecciona una fecha (ej: 1 año)
   - **Scopes**: Marca `write_repository` y `read_repository`
6. Click en **Create personal access token**
7. **IMPORTANTE**: Copia el token inmediatamente (solo se muestra una vez)

### Opción B: Usar SSH Keys (Recomendado para uso frecuente)

```bash
# Generar clave SSH (si no tienes una)
ssh-keygen -t ed25519 -C "tu.email@ibm.com"

# Copiar la clave pública
cat ~/.ssh/id_ed25519.pub

# Agregar la clave en GitLab:
# 1. Ve a Settings → SSH Keys
# 2. Pega la clave pública
# 3. Dale un título descriptivo
# 4. Click en "Add key"
```

## 📦 Paso 3: Crear Repositorio en IBM GitLab

1. Ve a https://github.ibm.com
2. Click en **New project** (botón verde)
3. Selecciona **Create blank project**
4. Configura:
   - **Project name**: `tunal-gpu-automation`
   - **Project slug**: `tunal-gpu-automation`
   - **Visibility Level**: **Private** (recomendado)
   - **Initialize repository with a README**: NO marcar
5. Click en **Create project**
6. Copia la URL del repositorio (aparecerá en la página)

## 🚀 Paso 4: Subir el Proyecto

### Opción A: Usando HTTPS con Token

```bash
# 1. Limpiar carpeta temporal (opcional)
rm -rf .github_cleanup/

# 2. Inicializar repositorio Git
git init

# 3. Agregar archivos
git add .

# 4. Verificar que config.json NO esté incluido
git status
# Debe mostrar solo 14 archivos, NO debe aparecer config.json

# 5. Hacer commit inicial
git commit -m "Initial commit: IBM Cloud VPC GPU Instance Manager

- Multi-zone failover capability
- Snapshot-based recovery
- COS integration for state management
- Scheduled start/stop operations
- VPN Site-to-Site support"

# 6. Agregar remote (reemplaza con tu URL)
git remote add origin https://github.ibm.com/tu-usuario/tunal-gpu-automation.git

# 7. Configurar rama principal
git branch -M main

# 8. Push usando token (te pedirá usuario y contraseña)
# Usuario: tu w3id
# Password: el token que generaste en el Paso 2
git push -u origin main
```

### Opción B: Usando SSH (Si configuraste SSH keys)

```bash
# 1-5. Igual que la Opción A

# 6. Agregar remote con SSH (reemplaza con tu usuario)
git remote add origin git@github.ibm.com:tu-usuario/tunal-gpu-automation.git

# 7. Configurar rama principal
git branch -M main

# 8. Push (no pedirá contraseña si SSH está configurado)
git push -u origin main
```

## 🔐 Paso 5: Guardar Credenciales (Opcional)

Para no tener que ingresar el token cada vez:

```bash
# Guardar credenciales en cache por 1 hora
git config --global credential.helper 'cache --timeout=3600'

# O guardar permanentemente (menos seguro)
git config --global credential.helper store
```

## ✅ Paso 6: Verificar

1. Ve a tu repositorio en https://github.ibm.com
2. Deberías ver todos los archivos
3. Verifica que **config.json NO esté presente**
4. Verifica que **config.json.example SÍ esté presente**

## 📝 Comandos Útiles para el Futuro

```bash
# Ver estado del repositorio
git status

# Ver archivos que se subirán
git add -n .

# Agregar cambios
git add .

# Hacer commit
git commit -m "Descripción de cambios"

# Subir cambios
git push

# Ver historial
git log --oneline

# Ver remote configurado
git remote -v
```

## 🔄 Actualizar el Repositorio Después

```bash
# 1. Hacer cambios en archivos

# 2. Ver qué cambió
git status
git diff

# 3. Agregar cambios
git add .

# 4. Commit
git commit -m "Descripción de los cambios"

# 5. Push
git push
```

## ⚠️ Recordatorios Importantes

1. **NUNCA** hagas commit de `config.json` con credenciales reales
2. El `.gitignore` ya está configurado para proteger archivos sensibles
3. Usa tokens con fecha de expiración por seguridad
4. Revoca tokens que ya no uses
5. Si accidentalmente subes credenciales:
   - Revoca inmediatamente las credenciales
   - Usa `git filter-branch` o BFG Repo-Cleaner para limpiar el historial
   - Genera nuevas credenciales

## 🆘 Solución de Problemas

### Error: "Authentication failed"
```bash
# Verifica que el token sea correcto
# Genera un nuevo token si es necesario
# Asegúrate de usar tu w3id como usuario
```

### Error: "Permission denied (publickey)"
```bash
# Verifica que la clave SSH esté agregada en GitLab
ssh -T git@github.ibm.com
```

### Error: "Repository not found"
```bash
# Verifica la URL del repositorio
git remote -v

# Actualiza la URL si es necesario
git remote set-url origin <nueva-url>
```

## 📚 Recursos Adicionales

- IBM GitLab: https://github.ibm.com
- Documentación Git: https://git-scm.com/doc
- IBM Git Support: https://w3.ibm.com/help/#/article/git

---

**¡Listo!** Tu proyecto está ahora en IBM Git y listo para colaboración 🚀