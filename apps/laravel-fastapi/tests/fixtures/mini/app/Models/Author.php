<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;
use Illuminate\Support\Facades\Hash;

class Author extends Model
{
    protected $fillable = ['name', 'password'];

    protected $hidden = ['password'];

    public function posts()
    {
        return $this->hasMany(Post::class);
    }

    public static function cadastrar(array $dados): self
    {
        $dados['password'] = Hash::make($dados['password']);

        return static::create($dados);
    }
}
