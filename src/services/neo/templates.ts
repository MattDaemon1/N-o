import type { SessionConfig } from './types';

export const SESSION_TEMPLATES: Array<{ id: string; label: string; config: SessionConfig }> = [
  {
    id: 'api-rest',
    label: 'Architecture API REST & HTTP',
    config: {
      name: 'Concevoir des API REST fiables',
      topic: 'Méthodes HTTP, idempotence et codes de statut',
      level: 'Intermédiaire',
      objectives:
        'Distinguer PUT et PATCH, comprendre l’idempotence et choisir les codes HTTP adaptés aux erreurs métier.',
      participantsCount: 14,
      durationMinutes: 90,
      cooldownSeconds: 20,
    },
  },
  {
    id: 'cyber-auth',
    label: 'Sécurité & Authentification Web',
    config: {
      name: 'Fondamentaux de la sécurité applicative',
      topic: 'OAuth 2.0, JWT et gestion des sessions',
      level: 'Mixte',
      objectives:
        'Différencier authentification et autorisation, comprendre le rôle du token de rafraîchissement et sécuriser les cookies.',
      participantsCount: 18,
      durationMinutes: 120,
      cooldownSeconds: 20,
    },
  },
  {
    id: 'management-feedback',
    label: 'Management & Posture de Feedback',
    config: {
      name: 'Conduire des entretiens constructifs',
      topic: 'Méthode DESC et écoute active en équipe',
      level: 'Débutant',
      objectives:
        'Formuler un retour factuel sans jugement, désamorcer les réactions défensives et co-construire un plan d’action.',
      participantsCount: 10,
      durationMinutes: 60,
      cooldownSeconds: 25,
    },
  },
];
