#include "euklid/vector/translation.hpp"


Translation::Translation() {
    for (int i=0; i<4; i++) {
        for (int j=0; j<4; j++) {
            this->matrix[i][j] = 0;
        }
    }
    this->matrix[3][3] = 1;
}

Translation::Translation(Translation::matrix_type matrix) : matrix(matrix) {}

Translation Translation::rotation(double angle, Vector3D axis) {
    // see http://en.wikipedia.org/wiki/SO%284%29#The_Euler.E2.80.93Rodrigues_formula_for_3D_rotations"""
    auto result = Translation();
    double a = cos(angle / 2);

    axis.normalize();

    double b = -axis.get_item(0) * sin(angle/2);
    double c = -axis.get_item(1) * sin(angle/2);
    double d = -axis.get_item(2) * sin(angle/2);

    result.matrix[0][0] = a*a + b*b - c*c - d*d;
    result.matrix[0][1] = 2* (b*c - a*d);
    result.matrix[0][2] = 2 * (b*d + a*c);

    result.matrix[1][0] = 2 * (b*c + a*d);
    result.matrix[1][1] = a*a + c*c - b*b - d*d;
    result.matrix[1][2] = 2 * (c*d - a*b);

    result.matrix[2][0] = 2 * (b*d - a*c);
    result.matrix[2][1] = 2 * (c*d + a*b);
    result.matrix[2][2] = a*a + d*d - b*b - c*c;

    result.matrix[3][3] = 1;

    return result;
}

Translation Translation::translation(const Vector3D& translation) {
    auto result = Translation();

    for (int i=0; i<3; i++) {
        result.matrix[i][i] = 1;
        result.matrix[3][i] = translation.get_item(i);
    }
    return result;
}

Translation Translation::translation(const Vector2D& translation) {
    auto result = Translation();

    for (int i=0; i<2; i++) {
        result.matrix[i][i] = 1;
        result.matrix[3][i] = translation.get_item(i);
    }
    return result;

}

Translation Translation::scale(double amount) {
    auto result = Translation();

    for (int i=0; i<3; i++) {
        result.matrix[i][i] = amount;
    }
    return result;
}

Translation Translation::chain(const Translation& t2) const {
    auto result = Translation();

    for (int row=0; row<4; row++) {
        for (int column=0; column<4; column++){
            double value = 0;
            for (int i=0; i<4; i++) {
                value += this->matrix[row][i] * t2.matrix[i][column];
            }
            result.matrix[row][column] = value;
        }
    }
    
    result.matrix[3][3] = 1;

    return result;
}


Vector3D Translation::apply(const Vector3D& vector) const {
    Vector3D result;

    for (int i=0; i<3; i++) {
        double value = this->matrix[3][i];
        for (int j=0; j<3; j++) {
            value += this->matrix[i][j] * vector.get_item(j);
        }
        result.set_item(i, value);
    }

    return result;
}


Vector2D Translation::apply(const Vector2D& vector) const {
    Vector2D result;

    for (int i=0; i<2; i++) {
        double value = this->matrix[3][i];
        for (int j=0; j<2; j++) {
            value += this->matrix[i][j] * vector.get_item(j);
        }
        result.set_item(i, value);
    }

    return result;
}
