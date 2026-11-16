# Diagramas técnicos — Módulo `users`, roles y seguridad

Documentación visual del módulo de Usuarios, Roles y Seguridad, derivada de
`specs/users_spec.md` y del código real de `backend/src/modules/users/`,
`backend/src/core/security.py` y `frontend/src/` (autenticación, guardias y
administración).

| Diagrama | Qué responde |
| --- | --- |
| Clases | Qué entidades existen, cómo se relacionan y qué servicios gobiernan credenciales, bloqueo y módulos permitidos |
| Componentes | Cómo viaja una petición desde React y el store de sesión hasta FastAPI, el núcleo de seguridad y PostgreSQL |
| Secuencia | Qué ocurre desde el CAPTCHA hasta la autorización de un módulo, incluyendo bloqueo, anti-timing y RBAC |

> **Nota de implementación:** el frontend no usa Zustand. La sesión vive en
> `frontend/src/store/authStore.ts`, un store propio basado en
> `useSyncExternalStore` y persistido en `localStorage`. El diagrama de
> componentes refleja esa decisión real.

---

## 1. Diagrama de clases

Entidades SQLAlchemy (`models.py`), el enum `RoleEnum`, la capa de servicio
(`services.py`), el núcleo de seguridad (`core/security.py`) y el seeding
canónico de roles (`seeding.py`). Los tipos corresponden al modelo ORM:
`UUID` para claves primarias y foráneas, `datetime` con zona horaria,
`JSONB` para `allowed_modules` y `str` para el hash Argon2id.

```mermaid
classDiagram

    class Base {
        <<abstract>>
        +metadata
    }

    class RoleEnum {
        <<enumeration>>
        ADMINISTRATOR
        INVENTORY
        SALES
        PURCHASING
        ACCOUNTING
        HR
        MANUFACTURING
    }

    class Role {
        +UUID id
        +RoleEnum name
        +str description
        +list~str~ allowed_modules
        +datetime created_at
        +list~User~ users
    }

    class User {
        +UUID id
        +str email
        +str username
        +str full_name
        +str hashed_password
        +UUID role_id
        +bool is_active
        +int failed_login_attempts
        +datetime locked_until
        +datetime created_at
        +datetime updated_at
        +Role role
        -normalize_email(value) str
        -normalize_username(value) str
    }

    class UserService {
        <<service>>
        +authenticate_user(db, identifier, password, captcha_token, captcha_answer) LoginResult
        +refresh_access_token(db, refresh_token) AccessTokenResult
        +list_roles(db) list~Role~
        +create_user(db, payload) User
        +list_users(db, skip, limit, role, is_active, search) list~User~
        +update_user(db, user_id, payload) User
        +reset_user_password(db, user_id, payload) User
        -find_user_for_login(db, identifier) User
        -ensure_identity_available(db, email, username, exclude_id) None
        -escape_like(value) str
        -as_utc(value) datetime
    }

    class SecurityCore {
        <<service>>
        +validate_password_strength(password) str
        +hash_password(password) str
        +verify_password(plain, hashed) bool
        +verify_dummy_password() None
        +create_access_token(subject, expires_delta) str
        +create_refresh_token(subject, expires_delta) str
        +create_token_pair(subject) TokenPair
        +decode_access_token(token) dict
        +decode_refresh_token(token) dict
        +generate_captcha() CaptchaChallenge
        +validate_captcha(token, answer) None
        +get_current_user(credentials, db) User
        +get_current_active_user(user) User
        +require_roles(allowed_roles) Callable
    }

    class RoleSeeding {
        <<service>>
        +ROLE_SEEDS tuple
        +seed_users_module(db) SeedReport
        +users_tables_ready() bool
        +seed_users_on_startup() None
        -sync_roles(db) tuple
        -ensure_superuser(db) bool
        -acquire_seed_lock(db) None
    }

    Base <|-- Role
    Base <|-- User

    Role "1" --> "0..*" User : asignado a · FK ON DELETE RESTRICT
    Role --> RoleEnum : name persistido en minúsculas
    UserService ..> User : credenciales · bloqueo · CRUD
    UserService ..> Role : catálogo · role_id · allowed_modules
    UserService ..> SecurityCore : hashing · JWT · CAPTCHA · RBAC
    RoleSeeding ..> Role : sincroniza los 7 roles canónicos
    RoleSeeding ..> User : crea el superusuario inicial

    SecurityCore ..> RoleEnum : require_roles recibe roles permitidos
    SecurityCore ..> User : resuelve el usuario desde el claim sub

    note for Role "UNIQUE name · allowed_modules en JSONB · matriz canónica del seeding"
    note for User "UNIQUE email y username · Argon2id en hashed_password"
    note for User "5 fallos consecutivos fijan locked_until = now + 15 min"
    note for RoleEnum "7 valores · SAEnum values_callable guarda minúsculas"
    note for UserService "CAPTCHA antes de consultar la base · dummy hash si el usuario no existe"
    note for SecurityCore "Argon2id · PyJWT access 30 min y refresh 7 días · itsdangerous CAPTCHA 180 s"
```

### Lectura del diagrama

- **`Role` es el catálogo autoritativo.** `allowed_modules` es una lista JSONB
  (`["inventory", "inventory:read", ...]`) que el seeding sincroniza en cada
  arranque; el sufijo `:read` habilita navegación de lectura sin escritura.
- **`RoleEnum` es estable y legible.** Los miembros Python van en mayúsculas,
  pero `values_callable` persiste `administrator`, `inventory`, `sales`, etc.,
  de modo que el enum nativo de PostgreSQL coincide con el contrato de la spec.
- **`User` concentra identidad y defensa.** `email` y `username` son únicos e
  indexados; `hashed_password` guarda Argon2id; `failed_login_attempts` y
  `locked_until` implementan el bloqueo temporal de 15 minutos tras 5 fallos.
- **`UserService.authenticate_user`** valida el CAPTCHA **antes** de consultar
  la base, busca por correo o usuario con `SELECT ... FOR UPDATE`, aplica el
  bloqueo, verifica el hash, reinicia el contador en éxito y emite el par de
  tokens. `verify_dummy_password()` cubre al usuario inexistente.
- **`UserService` también administra el ciclo de vida.** `create_user` valida
  el `role_id`, normaliza el correo y hashea la contraseña; `update_user` aplica
  solo los campos enviados; `reset_user_password` vuelve a hashear y limpia
  `failed_login_attempts`/`locked_until` para desbloquear la cuenta.
- **`SecurityCore.require_roles`** es la frontera de autorización: exige un
  usuario activo y permite el paso si su rol está en la lista o si es
  `ADMINISTRATOR` (bypass de superusuario).
- **`RoleSeeding`** mantiene la matriz canónica: crea los roles ausentes,
  actualiza descripción y `allowed_modules` si difieren y garantiza el
  superusuario inicial sin resetear su contraseña si ya existe.

---

## 2. Diagrama de componentes

Arquitectura full-stack: vistas React y guardias → store de sesión y hooks de
TanStack Query → cliente HTTP con Bearer y refresh → routers, esquemas Pydantic
y servicios FastAPI (con `slowapi`) → núcleo de seguridad (`Argon2id`, `PyJWT`,
`itsdangerous`) → tablas PostgreSQL. Incluye el router de inventario como
consumidor real de `require_roles`.

```mermaid
flowchart TB
    subgraph CLIENTE["Cliente · React 19 + Vite 8"]
        direction TB
        USUARIO["Usuario del ERP"]
        ROUTES["routes/index.tsx<br/>RequireAuth · RequireModule<br/>SessionValidator · IndexRedirect"]
        LOGIN["LoginPage.tsx<br/>identificador · contraseña<br/>CAPTCHA aritmético · safeReturnPath"]
        ADMIN["UserList.tsx y UserForm.tsx<br/>listado · alta · edición<br/>roles y activación"]
        LAYOUT["AppLayout.tsx<br/>menú filtrado por allowed_modules<br/>perfil y cierre de sesión"]
        DENIED["AccessDenied.tsx<br/>403 y módulos habilitados"]
    end

    subgraph ESTADO["Estado y datos del cliente"]
        direction TB
        STORE["store/authStore.ts<br/>useSyncExternalStore — sin Zustand<br/>access · refresh · perfil · permisos<br/>localStorage synapsisx.erp.auth.v1"]
        HOOKS["api/users.ts<br/>useCaptcha · useUsers · useRoles<br/>useCreateUser · useUpdateUser<br/>useResetUserPassword"]
        CLIENT["api/client.ts<br/>Bearer · ApiError<br/>refresh single-flight<br/>reintento único tras 401"]
        CONFIG["api/config.ts<br/>API_BASE_URL · buildQuery"]
    end

    subgraph API["API · FastAPI"]
        direction TB
        MAIN["main.py<br/>CORS · app.state.limiter<br/>handlers de excepción"]
        ROUTER["users/router.py<br/>auth_router · admin_router"]
        LIMIT["slowapi<br/>captcha 15/min<br/>login 5/min"]
        SCHEMAS["users/schemas.py<br/>Pydantic v2 · extra=forbid<br/>SecretStr · política 10–128"]
        SERVICES["users/services.py<br/>authenticate_user · refresh<br/>bloqueo 5 fallos · CRUD"]
        SECURITY["core/security.py<br/>Argon2id · PyJWT<br/>itsdangerous CAPTCHA<br/>get_current_active_user<br/>require_roles"]
        SEED["users/seeding.py<br/>7 roles · allowed_modules<br/>superusuario inicial"]
        INVENTORY["inventory/router.py<br/>require_roles INVENTORY<br/>lectura y escritura"]
    end

    subgraph DB["PostgreSQL 16"]
        direction TB
        T_ROLES["roles<br/>name UNIQUE<br/>allowed_modules JSONB"]
        T_USERS["users<br/>email y username UNIQUE<br/>hashed_password Argon2id<br/>failed_login_attempts · locked_until"]
        T_ENUM["enum role_enum<br/>7 valores en minúsculas"]
    end

    USUARIO --> ROUTES
    ROUTES --> LOGIN
    ROUTES --> LAYOUT
    ROUTES --> DENIED
    LAYOUT --> ADMIN
    LOGIN -->|"useCaptcha · login · getMe"| HOOKS
    ADMIN -->|"useUsers · useRoles · mutaciones"| HOOKS
    LOGIN -->|"setTokens · setUser"| STORE
    ROUTES -->|"useAuth · hasModuleAccess"| STORE
    LAYOUT -->|"useAuth · logout"| STORE
    HOOKS --> CLIENT
    CLIENT --> CONFIG
    CLIENT -->|"lee y actualiza tokens"| STORE
    CLIENT -->|"GET /api/v1/users/auth/captcha"| ROUTER
    CLIENT -->|"POST /api/v1/users/auth/login"| ROUTER
    CLIENT -->|"POST /api/v1/users/auth/refresh"| ROUTER
    CLIENT -->|"GET /api/v1/users/auth/me"| ROUTER
    CLIENT -->|"GET y POST /api/v1/users/"| ROUTER
    CLIENT -->|"Bearer en módulos operativos"| INVENTORY
    ROUTER --> LIMIT
    ROUTER --> SCHEMAS
    SCHEMAS -->|"payload validado"| SERVICES
    SERVICES --> SECURITY
    SERVICES -->|"SELECT · INSERT · UPDATE"| T_USERS
    SERVICES -->|"valida role_id y lee módulos"| T_ROLES
    SECURITY -->|"SELECT user + role por sub"| T_USERS
    INVENTORY --> SECURITY
    SEED -->|"upsert de roles"| T_ROLES
    SEED -->|"crea superusuario"| T_USERS
    T_ROLES --> T_ENUM
    MAIN --> ROUTER
    MAIN --> INVENTORY
    MAIN --> LIMIT
    MAIN -->|"400 · 401 · 403 · 409 · 423"| CLIENT
```

### Lectura del diagrama

- **El store es la fuente de sesión del cliente.** Guarda `accessToken`,
  `refreshToken` y el perfil con su rol y `allowed_modules`. Las guardias y el
  menú lo consumen, pero la autorización real sigue estando en FastAPI.
- **Un único cliente HTTP.** `apiRequest` añade el Bearer, traduce los errores a
  `ApiError` y, ante un 401, comparte una sola promesa de refresh para reintentar
  la petición original una vez. Si el refresh falla, limpia la sesión.
- **El CAPTCHA es stateless.** `itsdangerous` firma `{answer, nonce}`; el
  backend no guarda desafíos en base de datos ni en memoria.
- **`slowapi` protege la fuerza bruta y el abuso.** `GET /auth/captcha` admite
  15 peticiones/minuto y `POST /auth/login`, 5/minuto, ambos por IP remota.
- **Pydantic es el contrato de entrada.** `extra="forbid"` bloquea asignación
  masiva (`role`, `is_active`, `hashed_password`, etc.), `SecretStr` evita
  filtrar credenciales en logs y `StrongPassword` aplica la política 10–128.
- **El núcleo de seguridad es transversal.** Inventario y usuarios comparten
  `require_roles`; el primero lo usa para distinguir lectura/escritura y el
  segundo para restringir toda la administración a `ADMINISTRATOR`.
- **PostgreSQL materializa el contrato.** `role_enum` es un enum nativo,
  `allowed_modules` es JSONB, `users.email`/`users.username` son únicos y la FK
  `role_id` usa `ON DELETE RESTRICT` para no dejar cuentas sin rol.
- **El seeding es idempotente.** Se ejecuta en el `lifespan` de FastAPI y
  sincroniza la matriz canónica de roles sin tocar los datos de inventario.

---

## 3. Diagrama de secuencia — autenticación, bloqueo y autorización

Flujo completo desde `GET /api/v1/users/auth/captcha`, pasando por
`POST /api/v1/users/auth/login` con CAPTCHA, bloqueo anti-fuerza bruta y
protección anti-timing, hasta la evaluación de `require_roles` en el acceso a
un módulo del ERP.

```mermaid
sequenceDiagram
    autonumber
    actor Usuario
    participant UI as LoginPage · React
    participant STORE as authStore
    participant HTTP as apiRequest
    participant API as FastAPI · slowapi
    participant SEC as core/security
    participant SVC as users/services
    participant DB as PostgreSQL
    participant RBAC as require_roles
    participant INV as inventory/router

    Usuario->>UI: Abre /login
    UI->>HTTP: useCaptcha
    HTTP->>API: GET /api/v1/users/auth/captcha
    API->>API: slowapi 15/min por IP
    API->>SEC: generate_captcha()
    SEC->>SEC: secrets.randbelow + itsdangerous
    SEC-->>API: question + captcha_token firmado 180 s
    API-->>HTTP: 200 CaptchaResponse
    HTTP-->>UI: pregunta y token
    UI-->>Usuario: Muestra la suma aritmética

    Usuario->>UI: Envía identificador, contraseña y resultado
    UI->>HTTP: login(payload)
    HTTP->>API: POST /api/v1/users/auth/login
    API->>API: slowapi 5/min por IP
    API->>API: LoginRequest · extra=forbid · SecretStr
    API->>SVC: authenticate_user(...)

    SVC->>SEC: validate_captcha(token, answer)

    alt CAPTCHA inválido, manipulado o expirado
        SEC-->>SVC: CaptchaError
        SVC-->>API: CaptchaRejectedError
        API-->>HTTP: 400 CAPTCHA inválido o expirado
        HTTP-->>UI: ApiError · no consulta DB ni hash
        UI-->>Usuario: Pide un desafío nuevo
    else CAPTCHA válido
        SVC->>DB: SELECT user + role FOR UPDATE
        alt Usuario inexistente
            SVC->>SEC: verify_dummy_password()
            Note over SEC,DB: Argon2id descartable iguala el coste<br/>y evita enumeración por tiempo
            SVC-->>API: InvalidCredentialsError
            API-->>HTTP: 401 Credenciales inválidas
            HTTP-->>UI: Mensaje uniforme
        else Usuario existente
            alt locked_until mayor que now
                SVC-->>API: AccountLockedError
                API-->>HTTP: 423 Locked
                HTTP-->>UI: Cuenta bloqueada 15 min
            else Sin bloqueo vigente
                opt El bloqueo anterior expiró
                    SVC->>DB: Limpia contador y locked_until
                end
                SVC->>SEC: verify_password(password, hash Argon2id)
                alt Contraseña incorrecta
                    SVC->>DB: failed_login_attempts + 1
                    opt Llega a 5 intentos
                        SVC->>DB: locked_until = now + 15 min<br/>failed_login_attempts = 0
                    end
                    SVC-->>API: InvalidCredentialsError
                    API-->>HTTP: 401 Credenciales inválidas
                    HTTP-->>UI: 401 uniforme · quinto intento incluido
                else Contraseña correcta
                    alt is_active = false
                        SVC-->>API: InactiveUserError
                        API-->>HTTP: 403 Usuario inactivo
                        HTTP-->>UI: Limpia la sesión
                    else Cuenta activa
                        SVC->>DB: failed_login_attempts = 0 · locked_until = NULL
                        SVC->>SEC: create_token_pair(user.id)
                        SEC-->>SVC: access 30 min + refresh 7 días
                        SVC-->>API: LoginResult + role + allowed_modules
                        API-->>HTTP: 200 tokens · role · allowed_modules
                        HTTP-->>UI: Sesión emitida
                    end
                end
            end
        end
    end

    UI->>STORE: setTokens(access, refresh)
    Note over STORE: Persiste en localStorage<br/>synapsisx.erp.auth.v1

    UI->>HTTP: getMe con Bearer
    HTTP->>API: GET /api/v1/users/auth/me
    API->>SEC: get_current_active_user()
    SEC->>SEC: decode_access_token · PyJWT
    SEC->>DB: SELECT user + role por claim sub
    DB-->>SEC: perfil y allowed_modules
    SEC-->>API: User activo
    API-->>HTTP: 200 UserResponse sin hashed_password
    HTTP-->>UI: perfil autenticado
    UI->>STORE: setUser(profile)
    UI-->>Usuario: safeReturnPath según allowed_modules

    Usuario->>UI: Navega a /inventory
    UI->>UI: RequireModule · hasModuleAccess
    UI->>HTTP: useProducts()
    HTTP->>INV: GET /api/v1/inventory/products + Bearer
    INV->>RBAC: require_roles([INVENTORY])
    RBAC->>SEC: get_current_active_user()
    SEC->>SEC: decode_access_token · verifica is_active
    alt Rol permitido o ADMINISTRATOR
        RBAC-->>INV: usuario autorizado
        INV-->>HTTP: 200 datos de inventario
        HTTP-->>UI: renderiza la vista
    else Rol sin permiso
        RBAC-->>INV: HTTPException 403
        INV-->>HTTP: 403 No tienes permisos
        HTTP-->>UI: ApiError 403
        UI-->>Usuario: AccessDenied o mensaje
    end

    opt Access token expirado
        HTTP->>API: POST /api/v1/users/auth/refresh
        API->>SEC: decode_refresh_token()
        SEC-->>API: sub válido y cuenta activa
        API-->>HTTP: 200 nuevo access token
        HTTP->>INV: reintenta la petición una vez
    end
```

### Lectura del diagrama

- **El CAPTCHA se valida primero.** Si la firma, la antigüedad o la suma fallan,
  el flujo termina en 400 antes de consultar la base o el hash; un CAPTCHA
  rechazado no incrementa `failed_login_attempts`.
- **La búsqueda bloquea la fila.** `SELECT ... FOR UPDATE` serializa intentos
  concurrentes sobre el mismo usuario en PostgreSQL. En SQLite de pruebas el
  bloqueo se ignora de forma segura.
- **Anti-enumeración y anti-timing.** Usuario inexistente y contraseña
  incorrecta devuelven el mismo 401 (`Credenciales inválidas`); el primero
  ejecuta `verify_dummy_password()` para igualar el coste Argon2id.
- **Bloqueo real, no solo cosmético.** El quinto fallo fija
  `locked_until = now + 15 min` y reinicia el contador; ese quinto intento aún
  responde 401 uniforme y el siguiente responde **423 Locked**, incluso con la
  contraseña correcta. Al expirar, el estado se limpia antes de verificar.
- **La cuenta inactiva se distingue solo tras verificar la contraseña.** Así no
  se revela la existencia de una cuenta deshabilitada a quien no conoce la
  credencial.
- **Tokens con claims estrictos.** `PyJWT` exige `sub`, `type`, `iat` y `exp`;
  el access dura 30 minutos y el refresh 7 días. El frontend persiste ambos en
  `localStorage` (riesgo XSS asumido y documentado).
- **La guardia visual no sustituye al backend.** `RequireModule` oculta/bloquea
  rutas según `allowed_modules`, pero `require_roles` vuelve a validar el rol
  en FastAPI. Un `ADMINISTRATOR` pasa siempre por bypass.
- **Renovación transparente.** Ante un access token expirado, `apiRequest`
  comparte un único refresh, reintenta la petición una sola vez y limpia la
  sesión si el refresh falla. Un `403 {"detail":"Usuario inactivo"}` también
  cierra la sesión.

---

## Referencias

- Contrato funcional: `specs/users_spec.md` (§2 stack, §3 entidades, §4
  seguridad, §5 API, §6 escenarios OWASP).
- Backend: `backend/src/modules/users/{models,schemas,services,router,seeding}.py`,
  `backend/src/core/security.py`, `backend/src/core/config.py`,
  `backend/src/main.py`.
- Frontend: `frontend/src/store/authStore.ts`, `frontend/src/api/{client,config,users}.ts`,
  `frontend/src/modules/users/{LoginPage,UserList,UserForm,constants}.tsx`,
  `frontend/src/routes/{index,guards,modules,AccessDenied,ModulePlaceholder}.tsx`,
  `frontend/src/layouts/AppLayout.tsx`.
- Pruebas: `backend/tests/test_users_security.py` (7 escenarios OWASP),
  `test_users_security_core.py`, `test_users_auth_flow.py`,
  `test_users_admin.py` y `test_users_seeding.py`.
- Bitácora: `memory/users_memory.md`, `MEMORY.md`.
