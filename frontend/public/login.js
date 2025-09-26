document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('login-form');
    const errorMessage = document.getElementById('error-message');
    const usernameInput = document.getElementById('username');
    const passwordInput = document.getElementById('password');

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        errorMessage.textContent = '';
        const username = usernameInput.value;
        const password = passwordInput.value;

        try {
            const response = await fetch('/api/login', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ username: username, password: password }),
            });

            if (response.ok) {
                const data = await response.json();
                // Store the logged-in user and the active user, then redirect
                localStorage.setItem('loggedInUser', data.user);
                localStorage.setItem('activeUser', data.user);
                window.location.href = '/';
            } else {
                errorMessage.textContent = 'Falscher Benutzername oder Passwort.';
                usernameInput.focus();
            }
        } catch (error) {
            errorMessage.textContent = 'Ein Fehler ist aufgetreten. Bitte später erneut versuchen.';
            console.error('Login error:', error);
        }
    });
});