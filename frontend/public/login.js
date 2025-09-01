document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('login-form');
    const errorMessage = document.getElementById('error-message');
    const passwordInput = document.getElementById('password');

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        errorMessage.textContent = '';
        const password = passwordInput.value;

        try {
            const response = await fetch('/api/login', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ password: password }),
            });

            if (response.ok) {
                // On successful login, the backend sets the cookie and we can redirect
                window.location.href = '/';
            } else {
                errorMessage.textContent = 'Falsches Passwort. Bitte erneut versuchen.';
                passwordInput.focus();
            }
        } catch (error) {
            errorMessage.textContent = 'Ein Fehler ist aufgetreten. Bitte später erneut versuchen.';
            console.error('Login error:', error);
        }
    });
});