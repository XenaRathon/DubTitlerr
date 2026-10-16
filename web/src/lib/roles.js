/** The role gate for rendering: admin-only controls show for the admin role and for nothing else (fails closed). */
/** @param {unknown} role */
export const isAdmin = (role) => role === 'admin';
