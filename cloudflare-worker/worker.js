/**
 * Worker Cloudflare "relais de licence" pour Zenkai Core.
 *
 * Rôle : servir d'intermédiaire entre l'app (cliente, non fiable) et le
 * Gist GitHub privé qui contient le registre des licences. L'app ne lit
 * plus jamais le Gist directement : elle POST { key, hardware_id } ici, et
 * c'est CE Worker (jamais le client) qui décide si la clé est valide et
 * qui écrit le hardware_id verrouillé dans le Gist via un token GitHub
 * secret — un token que le client ne voit jamais, donc qu'il ne peut
 * jamais utiliser pour modifier le Gist lui-même (contournement impossible
 * côté client, contrairement à une vérification purement locale).
 *
 * Variables d'environnement attendues (à configurer dans le dashboard
 * Cloudflare, voir CLAUDE.md du dépôt principal) :
 *   - GITHUB_TOKEN   (secret) : token GitHub avec la permission "gist"
 *   - GIST_ID        (variable) : identifiant du Gist (dans son URL)
 *   - GIST_FILENAME  (variable) : nom du fichier JSON dans le Gist
 *                                  (ex: "zenkai_licenses.json")
 */

const GITHUB_API = "https://api.github.com";
// GitHub exige un User-Agent explicite sur toutes ses requêtes API, sinon
// il répond 403 — un simple nom d'app suffit, pas besoin d'un vrai navigateur.
const USER_AGENT = "ZenkaiCore-License-Worker";

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    // Seule route exposée : POST /activate. Tout le reste (mauvaise méthode,
    // mauvais chemin) est refusé explicitement plutôt que de tomber dans un
    // comportement par défaut ambigu.
    if (url.pathname !== "/activate") {
      return jsonResponse({ status: "error", message: "Not found" }, 404);
    }
    if (request.method !== "POST") {
      return jsonResponse({ status: "error", message: "Method not allowed" }, 405);
    }

    let body;
    try {
      body = await request.json();
    } catch (err) {
      return jsonResponse({ status: "error", message: "Invalid JSON body" }, 400);
    }

    const key = normalizeKey(body && body.key);
    const hardwareId = normalizeHardwareId(body && body.hardware_id);
    if (!key || !hardwareId) {
      return jsonResponse({ status: "error", message: "Missing key or hardware_id" }, 400);
    }

    if (!env.GITHUB_TOKEN || !env.GIST_ID || !env.GIST_FILENAME) {
      // Erreur de configuration du Worker lui-même (secret/variable manquant) :
      // jamais la faute du client, mais il ne doit surtout pas être débloqué
      // par erreur pour autant -> statut générique "error" (le client le
      // traite comme une panne réseau/serveur, pas comme une clé invalide).
      return jsonResponse({ status: "error", message: "Worker misconfigured" }, 500);
    }

    let registry;
    try {
      registry = await fetchRegistry(env);
    } catch (err) {
      return jsonResponse({ status: "error", message: "Gist unreachable" }, 502);
    }

    const entry = registry[key];
    if (!entry) {
      return jsonResponse({ status: "not_found" });
    }
    if (entry.actif === false) {
      return jsonResponse({ status: "deactivated" });
    }

    // Pas encore d'appareil enregistré sur cette clé : première activation,
    // on verrouille cet appareil dessus immédiatement.
    if (!entry.hardware_id) {
      entry.hardware_id = hardwareId;
      try {
        await updateRegistry(env, registry);
      } catch (err) {
        return jsonResponse({ status: "error", message: "Gist update failed" }, 502);
      }
      return jsonResponse({ status: "valid", nom: entry.nom || "" });
    }

    // Même appareil qui revérifie (démarrage de l'app, bouton Revérifier) :
    // toujours valide, on n'écrit rien de plus dans le Gist.
    if (entry.hardware_id === hardwareId) {
      return jsonResponse({ status: "valid", nom: entry.nom || "" });
    }

    // Hardware_id déjà enregistré et différent -> un autre appareil possède
    // déjà cette clé, celui-ci est bloqué.
    return jsonResponse({ status: "already_used" });
  },
};

/** Uniformise la clé reçue (espaces, casse) pour matcher le format du registre. */
function normalizeKey(key) {
  return typeof key === "string" ? key.trim().toUpperCase() : "";
}

/** Le hardware_id est déjà un hash côté client : on ne fait que le nettoyer. */
function normalizeHardwareId(hardwareId) {
  return typeof hardwareId === "string" ? hardwareId.trim() : "";
}

/** Petit utilitaire pour toujours répondre en JSON avec le bon Content-Type. */
function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/** Récupère le Gist et retourne le registre déjà parsé (objet clé -> entrée). */
async function fetchRegistry(env) {
  const response = await fetch(`${GITHUB_API}/gists/${env.GIST_ID}`, {
    headers: {
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      Accept: "application/vnd.github+json",
      "User-Agent": USER_AGENT,
    },
  });
  if (!response.ok) {
    throw new Error(`GitHub API GET ${response.status}`);
  }
  const data = await response.json();
  const file = data.files && data.files[env.GIST_FILENAME];
  if (!file || typeof file.content !== "string") {
    throw new Error("Fichier attendu absent du Gist");
  }
  const parsed = JSON.parse(file.content);
  if (!parsed || typeof parsed !== "object") {
    throw new Error("Contenu du Gist mal formé");
  }
  return parsed;
}

/** Réécrit le Gist entier avec le registre mis à jour (ex: nouveau hardware_id). */
async function updateRegistry(env, registry) {
  const response = await fetch(`${GITHUB_API}/gists/${env.GIST_ID}`, {
    method: "PATCH",
    headers: {
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      Accept: "application/vnd.github+json",
      "User-Agent": USER_AGENT,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      files: {
        [env.GIST_FILENAME]: {
          content: JSON.stringify(registry, null, 2),
        },
      },
    }),
  });
  if (!response.ok) {
    throw new Error(`GitHub API PATCH ${response.status}`);
  }
}
