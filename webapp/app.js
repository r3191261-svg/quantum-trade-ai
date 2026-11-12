const tg = window.Telegram?.WebApp;

if (tg) {
    tg.ready();
    tg.expand();

    tg.setHeaderColor("#050b18");
    tg.setBackgroundColor("#050b18");
}

// ДЕМОНСТРАЦИОННЫЕ ДАННЫЕ ГРАФИКА
// Позже подключим реальный источник котировок.

const chartCanvas = document.getElementById("marketChart");

const chartLabels = Array.from(
    { length: 30 },
    (_, i) => `${i + 1}`
);

const chartValues = [
    67320, 67380, 67290, 67410, 67370,
    67500, 67460, 67540, 67610, 67580,
    67670, 67620, 67710, 67650, 67800,
    67750, 67830, 67790, 67900, 67850,
    67940, 67890, 68010, 67970, 68050,
    68000, 68100, 68060, 68150, 68200
];

if (chartCanvas && window.Chart) {
    const ctx = chartCanvas.getContext("2d");

    const gradient = ctx.createLinearGradient(0, 0, 0, 200);
    gradient.addColorStop(0, "rgba(22,140,255,0.35)");
    gradient.addColorStop(1, "rgba(22,140,255,0)");

    new Chart(ctx, {
        type: "line",

        data: {
            labels: chartLabels,

            datasets: [{
                data: chartValues,
                borderColor: "#168cff",
                backgroundColor: gradient,
                borderWidth: 2,
                fill: true,
                tension: 0.35,
                pointRadius: 0
            }]
        },

        options: {
            responsive: true,
            maintainAspectRatio: false,

            plugins: {
                legend: {
                    display: false
                }
            },

            scales: {
                x: {
                    display: false
                },

                y: {
                    display: true,

                    grid: {
                        color: "rgba(120,160,220,0.08)"
                    },

                    ticks: {
                        color: "#8294b3",
                        font: {
                            size: 9
                        }
                    }
                }
            }
        }
    });
}

// ДЕМОНСТРАЦИОННАЯ ЦЕНА
// Не является реальной котировкой.

document.getElementById("btcPrice").textContent = "$68,200";

document.getElementById("btcChange").textContent = "+1.25%";

// ПЕРЕКЛЮЧЕНИЕ РАЗДЕЛОВ

const content = document.getElementById("contentCard");

const pages = {

    binary: {
        title: "⚡ БИНАРНЫЕ ОПЦИОНЫ",
        text: "Здесь будут отображаться сигналы, автоматически полученные из канала SIGNALS PRO."
    },

    news: {
        title: "🌐 НОВОСТИ",
        text: "Здесь появятся новости финансовых рынков и важные события."
    },

    statistics: {
        title: "📊 СТАТИСТИКА",
        text: "Количество сигналов, успешные сделки, неудачные сделки и процент успешности."
    },

    history: {
        title: "🕘 ИСТОРИЯ СИГНАЛОВ",
        text: "Архив полученных сигналов и подтверждённых результатов."
    },

    autobot: {
        title: "🤖 АВТОМАТИЧЕСКИЙ БОТ",

        text: `
            QUANTUM TRADE AI — АВТОТРЕЙД<br><br>

            Для подключения автоматического бота
            необходимо иметь аккаунт у брокера Intrade Bar.<br><br>

            🔹 Если у вас ещё нет аккаунта,
            пройдите регистрацию:<br>

            <a class="action-link"
               href="https://go.intrade.bar/n4FmpAFBYfvE"
               target="_blank">
               РЕГИСТРАЦИЯ
            </a><br><br>

            🔹 Если у вас уже есть аккаунт,
            обратитесь в поддержку:<br>

            <a class="action-link"
               href="https://t.me/copy_broker_BO_bot"
               target="_blank">
               ПОДКЛЮЧИТЬ БОТА
            </a>
        `
    },

    profile: {
        title: "👤 МОЙ ПРОФИЛЬ",
        text: "Здесь будет информация о пользователе, его Telegram ID и настройках аккаунта."
    },

    settings: {
        title: "⚙️ НАСТРОЙКИ",
        text: "Здесь будут настройки уведомлений, языка и отображения терминала."
    }

};

document.querySelectorAll(".menu-button").forEach(button => {

    button.addEventListener("click", () => {

        const page = button.dataset.page;
        const selected = pages[page];

        if (!selected) return;

        content.innerHTML = `
            <div class="content-title">${selected.title}</div>
            <p>${selected.text}</p>
        `;

        content.scrollIntoView({
            behavior: "smooth",
            block: "nearest"
        });

        if (tg) {
            tg.HapticFeedback?.impactOccurred("light");
        }

    });

});